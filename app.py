import os
import json
import hashlib
from flask import Flask, request, jsonify, send_file, make_response
from werkzeug.utils import secure_filename
import logging
from pythonjsonlogger import jsonlogger

# 配置日志
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

app = Flask(__name__)

# 配置
REGISTRY_PATH = "data"
os.makedirs(REGISTRY_PATH, exist_ok=True)
os.makedirs(os.path.join(REGISTRY_PATH, "blobs"), exist_ok=True)
os.makedirs(os.path.join(REGISTRY_PATH, "uploads"), exist_ok=True)
os.makedirs(os.path.join(REGISTRY_PATH, "manifests"), exist_ok=True)

# 支持的媒体类型
SUPPORTED_MANIFEST_TYPES = [
    'application/vnd.docker.distribution.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.oci.image.index.v1+json'
]

def get_blob_path(digest):
    return os.path.join(REGISTRY_PATH, "blobs", digest.replace('sha256:', ''))

def get_manifest_path(name, reference):
    # 如果reference是sha256开头，去掉前缀
    if reference.startswith('sha256:'):
        reference = reference[7:]
    return os.path.join(REGISTRY_PATH, "manifests", name, reference)

def get_upload_path(upload_id):
    return os.path.join(REGISTRY_PATH, "uploads", upload_id)

def get_manifest_by_digest(name, digest):
    manifest_dir = os.path.join(REGISTRY_PATH, "manifests", name)
    if not os.path.exists(manifest_dir):
        return None
    
    # 遍历目录下的所有文件
    for filename in os.listdir(manifest_dir):
        filepath = os.path.join(manifest_dir, filename)
        if os.path.isfile(filepath):
            with open(filepath, 'rb') as f:
                content = f.read()
                current_digest = f'sha256:{hashlib.sha256(content).hexdigest()}'
                if current_digest == digest:
                    return content
    return None

def get_manifest_content_type(accept_header):
    if not accept_header:
        return 'application/vnd.docker.distribution.manifest.v2+json'
    
    # 按照优先级排序支持的类型
    for media_type in SUPPORTED_MANIFEST_TYPES:
        if media_type in accept_header:
            return media_type
    
    return 'application/vnd.docker.distribution.manifest.v2+json'

# API v2 基础检查
@app.route('/v2/')
def v2_check():
    response = make_response(jsonify({}))
    response.headers['Docker-Distribution-API-Version'] = 'registry/2.0'
    return response

# Blob 上传初始化
@app.route('/v2/<path:name>/blobs/uploads/', methods=['POST'])
def init_blob_upload(name):
    # 检查是否已经存在相同的blob
    digest = request.args.get('digest')
    if digest:
        blob_path = get_blob_path(digest)
        if os.path.exists(blob_path):
            response = make_response('')
            response.headers['Docker-Content-Digest'] = digest
            response.headers['Location'] = f'/v2/{name}/blobs/{digest}'
            response.status_code = 201
            return response

    upload_id = hashlib.sha256(os.urandom(32)).hexdigest()
    upload_path = get_upload_path(upload_id)
    os.makedirs(os.path.dirname(upload_path), exist_ok=True)
    
    # 创建一个空文件
    open(upload_path, 'wb').close()
    
    response = make_response('')
    response.headers['Location'] = f'/v2/{name}/blobs/uploads/{upload_id}'
    response.headers['Range'] = '0-0'
    response.headers['Docker-Upload-UUID'] = upload_id
    response.status_code = 202
    return response

# Blob 上传
@app.route('/v2/<path:name>/blobs/uploads/<upload_id>', methods=['PATCH'])
def upload_blob(name, upload_id):
    upload_path = get_upload_path(upload_id)
    
    if not os.path.exists(upload_path):
        return jsonify({'errors': [{'code': 'BLOB_UPLOAD_UNKNOWN'}]}), 404
    
    # 获取当前文件大小
    current_size = os.path.getsize(upload_path)
    
    # 获取Content-Range头部
    content_range = request.headers.get('Content-Range')
    if content_range:
        try:
            start, end = map(int, content_range.split('-'))
            if start != current_size:
                return jsonify({'errors': [{'code': 'BLOB_UPLOAD_INVALID'}]}), 400
        except:
            return jsonify({'errors': [{'code': 'BLOB_UPLOAD_INVALID'}]}), 400
    
    # 写入数据
    with open(upload_path, 'ab') as f:
        f.write(request.data)
    
    # 更新后的文件大小
    new_size = os.path.getsize(upload_path)
    
    response = make_response('')
    response.headers['Location'] = f'/v2/{name}/blobs/uploads/{upload_id}'
    response.headers['Range'] = f'0-{new_size - 1}'
    response.headers['Docker-Upload-UUID'] = upload_id
    response.status_code = 202
    return response

# Blob 上传完成
@app.route('/v2/<path:name>/blobs/uploads/<upload_id>', methods=['PUT'])
def complete_blob_upload(name, upload_id):
    upload_path = get_upload_path(upload_id)
    
    if not os.path.exists(upload_path):
        return jsonify({'errors': [{'code': 'BLOB_UPLOAD_UNKNOWN'}]}), 404
    
    digest = request.args.get('digest')
    if not digest:
        return jsonify({'errors': [{'code': 'DIGEST_INVALID'}]}), 400
    
    # 计算上传文件的实际摘要
    with open(upload_path, 'rb') as f:
        actual_digest = f'sha256:{hashlib.sha256(f.read()).hexdigest()}'
    
    # 验证摘要
    if digest != actual_digest:
        os.remove(upload_path)
        return jsonify({'errors': [{'code': 'DIGEST_INVALID'}]}), 400
    
    blob_path = get_blob_path(digest)
    os.makedirs(os.path.dirname(blob_path), exist_ok=True)
    
    # 如果blob已存在，直接删除上传的文件
    if os.path.exists(blob_path):
        os.remove(upload_path)
    else:
        os.rename(upload_path, blob_path)
    
    response = make_response('')
    response.headers['Docker-Content-Digest'] = digest
    response.headers['Location'] = f'/v2/{name}/blobs/{digest}'
    response.status_code = 201
    return response

# 获取 Blob
@app.route('/v2/<path:name>/blobs/<digest>', methods=['GET', 'HEAD'])
def get_blob(name, digest):
    blob_path = get_blob_path(digest)
    if not os.path.exists(blob_path):
        return jsonify({'errors': [{'code': 'BLOB_UNKNOWN'}]}), 404
    
    if request.method == 'HEAD':
        response = make_response('')
        response.headers['Docker-Content-Digest'] = digest
        response.headers['Content-Length'] = str(os.path.getsize(blob_path))
        response.headers['Content-Type'] = 'application/octet-stream'
        return response
    
    return send_file(
        blob_path,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=os.path.basename(blob_path)
    )

# 上传 Manifest
@app.route('/v2/<path:name>/manifests/<reference>', methods=['PUT'])
def put_manifest(name, reference):
    manifest_path = get_manifest_path(name, reference)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    
    content_type = request.headers.get('Content-Type', '')
    if not any(content_type.startswith(t) for t in SUPPORTED_MANIFEST_TYPES):
        return jsonify({'errors': [{'code': 'MANIFEST_INVALID', 'message': 'manifest invalid', 'detail': f'unsupported manifest media type: {content_type}'}]}), 400
    
    # 解析并验证 manifest 数据
    try:
        manifest_data = json.loads(request.data)
        if 'mediaType' in manifest_data and manifest_data['mediaType'] not in SUPPORTED_MANIFEST_TYPES:
            return jsonify({'errors': [{'code': 'MANIFEST_INVALID', 'message': 'manifest invalid', 'detail': f'unsupported manifest media type in content: {manifest_data["mediaType"]}'}]}), 400
    except json.JSONDecodeError:
        return jsonify({'errors': [{'code': 'MANIFEST_INVALID', 'message': 'manifest invalid', 'detail': 'invalid json'}]}), 400
    
    with open(manifest_path, 'wb') as f:
        f.write(request.data)
    
    digest = f'sha256:{hashlib.sha256(request.data).hexdigest()}'
    
    # 如果上传的是tag，创建一个指向digest的符号链接
    if not reference.startswith('sha256:'):
        digest_path = get_manifest_path(name, digest)
        if not os.path.exists(digest_path):
            try:
                os.link(manifest_path, digest_path)
            except OSError:
                # 如果硬链接失败，尝试复制文件
                with open(digest_path, 'wb') as f:
                    f.write(request.data)
    
    response = make_response('')
    response.headers['Docker-Content-Digest'] = digest
    response.headers['Location'] = f'/v2/{name}/manifests/{digest}'
    response.headers['Content-Type'] = content_type
    response.status_code = 201
    return response

# 获取 Manifest
@app.route('/v2/<path:name>/manifests/<reference>', methods=['GET', 'HEAD'])
def get_manifest(name, reference):
    manifest_path = get_manifest_path(name, reference)
    
    # 如果是通过digest请求，且文件不存在，尝试查找
    if reference.startswith('sha256:') and not os.path.exists(manifest_path):
        content = get_manifest_by_digest(name, reference)
        if content is None:
            return jsonify({'errors': [{'code': 'MANIFEST_UNKNOWN'}]}), 404
        data = content
    else:
        if not os.path.exists(manifest_path):
            return jsonify({'errors': [{'code': 'MANIFEST_UNKNOWN'}]}), 404
        with open(manifest_path, 'rb') as f:
            data = f.read()
    
    # 解析 manifest 数据以获取实际的 mediaType
    try:
        manifest_data = json.loads(data)
        # 确保使用 v2 格式
        if 'mediaType' not in manifest_data:
            manifest_data['mediaType'] = 'application/vnd.docker.distribution.manifest.v2+json'
            data = json.dumps(manifest_data).encode('utf-8')
        content_type = manifest_data.get('mediaType', 'application/vnd.docker.distribution.manifest.v2+json')
    except json.JSONDecodeError:
        content_type = 'application/vnd.docker.distribution.manifest.v2+json'
    
    digest = f'sha256:{hashlib.sha256(data).hexdigest()}'
    
    if request.method == 'HEAD':
        response = make_response('')
        response.headers['Docker-Content-Digest'] = digest
        response.headers['Content-Length'] = str(len(data))
        response.headers['Content-Type'] = content_type
        return response
    
    response = make_response(data)
    response.headers['Content-Type'] = content_type
    response.headers['Docker-Content-Digest'] = digest
    response.headers['Content-Length'] = str(len(data))
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 