import os
import json
import hashlib
from flask import Flask, request, jsonify, send_file, make_response
from werkzeug.utils import secure_filename
import logging
import shutil
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

# 列出仓库中的所有镜像
@app.route('/v2/_catalog', methods=['GET'])
def list_repositories():
    manifest_dir = os.path.join(REGISTRY_PATH, "manifests")
    repositories = []
    
    if os.path.exists(manifest_dir):
        repositories = [name for name in os.listdir(manifest_dir)
                      if os.path.isdir(os.path.join(manifest_dir, name))]
    
    n = request.args.get('n', type=int)
    last = request.args.get('last', '')
    
    if last:
        repositories = [r for r in repositories if r > last]
    if n is not None:
        repositories = repositories[:n]
    
    response = {
        'repositories': sorted(repositories)
    }
    
    return jsonify(response)

# 列出指定镜像的所有标签
@app.route('/v2/<path:name>/tags/list', methods=['GET'])
def list_tags(name):
    manifest_dir = os.path.join(REGISTRY_PATH, "manifests", name)
    if not os.path.exists(manifest_dir):
        return jsonify({'errors': [{'code': 'NAME_UNKNOWN'}]}), 404
    
    tags = []
    for item in os.listdir(manifest_dir):
        if os.path.isfile(os.path.join(manifest_dir, item)) and not item.startswith('sha256:'):
            tags.append(item)
    
    n = request.args.get('n', type=int)
    last = request.args.get('last', '')
    
    if last:
        tags = [t for t in tags if t > last]
    if n is not None:
        tags = tags[:n]
    
    response = {
        'name': name,
        'tags': sorted(tags)
    }
    
    return jsonify(response)

def _is_blob_referenced(digest, exclude_manifest=None):
    """检查一个blob是否被其他manifest引用
    
    Args:
        digest: blob的digest
        exclude_manifest: (name, reference, digest) 元组，表示要排除的manifest及其digest
    """
    manifest_dir = os.path.join(REGISTRY_PATH, "manifests")
    
    # 标准化 digest 格式
    if not digest.startswith('sha256:'):
        digest = f'sha256:{digest}'
    
    for repo in os.listdir(manifest_dir):
        repo_path = os.path.join(manifest_dir, repo)
        if os.path.isdir(repo_path):
            for filename in os.listdir(repo_path):
                manifest_path = os.path.join(repo_path, filename)
                # 跳过当前正在删除的manifest（包括tag和digest）
                if exclude_manifest:
                    name, ref, manifest_digest = exclude_manifest
                    if repo == name and (filename == ref or (manifest_digest and filename == manifest_digest[7:])):
                        continue
                
                if os.path.isfile(manifest_path):
                    try:
                        with open(manifest_path, 'rb') as f:
                            manifest_data = json.loads(f.read())
                            
                            # 检查 config blob
                            if manifest_data.get('config', {}).get('digest') == digest:
                                return True
                            
                            # 检查 layers
                            if 'layers' in manifest_data:
                                for layer in manifest_data['layers']:
                                    if layer.get('digest') == digest:
                                        return True
                            
                            # 检查 manifests (用于 manifest lists)
                            if 'manifests' in manifest_data:
                                for manifest in manifest_data['manifests']:
                                    if manifest.get('digest') == digest:
                                        return True
                    except:
                        continue
    return False

def _delete_unreferenced_blobs(manifest_data, exclude_manifest=None):
    """删除不再被引用的 blobs
    
    Args:
        manifest_data: manifest的JSON数据
        exclude_manifest: (name, reference, digest) 元组，表示要排除的manifest及其digest
    """
    # 收集所有相关的 blobs
    blobs_to_check = set()
    
    # 添加 config blob
    if 'config' in manifest_data and 'digest' in manifest_data['config']:
        blobs_to_check.add(manifest_data['config']['digest'])
    
    # 添加 layers
    if 'layers' in manifest_data:
        for layer in manifest_data['layers']:
            if 'digest' in layer:
                blobs_to_check.add(layer['digest'])
    
    # 添加 manifests (用于 manifest lists)
    if 'manifests' in manifest_data:
        for manifest in manifest_data['manifests']:
            if 'digest' in manifest:
                blobs_to_check.add(manifest['digest'])
    
    # 检查并删除不再被引用的 blobs
    for digest in blobs_to_check:
        if not _is_blob_referenced(digest, exclude_manifest):
            blob_path = get_blob_path(digest)
            if os.path.exists(blob_path):
                try:
                    os.remove(blob_path)
                    logger.info(f"Deleted unreferenced blob: {digest}")
                except Exception as e:
                    logger.error(f"Error deleting blob {digest}: {str(e)}")

# 删除镜像标签
@app.route('/v2/<path:name>/manifests/<reference>', methods=['DELETE'])
def delete_manifest(name, reference):
    manifest_path = get_manifest_path(name, reference)
    original_reference = reference
    
    # 如果是通过digest请求，且文件不存在，尝试查找
    if reference.startswith('sha256:') and not os.path.exists(manifest_path):
        content = get_manifest_by_digest(name, reference)
        if content is None:
            return jsonify({'errors': [{'code': 'MANIFEST_UNKNOWN'}]}), 404
        manifest_data = json.loads(content)
        manifest_content = content
    elif not os.path.exists(manifest_path):
        return jsonify({'errors': [{'code': 'MANIFEST_UNKNOWN'}]}), 404
    else:
        # 读取manifest内容
        with open(manifest_path, 'rb') as f:
            manifest_content = f.read()
            manifest_data = json.loads(manifest_content)
    
    try:
        # 使用原始内容计算manifest的digest
        manifest_digest = f'sha256:{hashlib.sha256(manifest_content).hexdigest()}'
        
        # 如果是tag引用，获取对应的digest路径
        if not original_reference.startswith('sha256:'):
            digest_path = get_manifest_path(name, manifest_digest)
            exclude_ref = (name, original_reference, manifest_digest)
        else:
            digest_path = manifest_path
            exclude_ref = (name, manifest_digest[7:], None)  # 去掉 'sha256:' 前缀
            
            # 如果是通过digest删除，找到并删除所有指向这个digest的tag
            manifest_dir = os.path.join(REGISTRY_PATH, "manifests", name)
            target_digest = original_reference[7:] if original_reference.startswith('sha256:') else original_reference
            
            if os.path.exists(manifest_dir):
                for tag in os.listdir(manifest_dir):
                    tag_path = os.path.join(manifest_dir, tag)
                    if os.path.isfile(tag_path) and not tag.startswith('sha256:'):
                        try:
                            # 检查硬链接是否指向同一个文件
                            if os.path.samefile(tag_path, manifest_path):
                                os.remove(tag_path)
                                logger.info(f"Deleted tag {tag} pointing to digest {original_reference}")
                        except Exception as e:
                            # 如果不是硬链接，读取内容比较
                            try:
                                with open(tag_path, 'rb') as f:
                                    tag_content = f.read()
                                    tag_digest = hashlib.sha256(tag_content).hexdigest()
                                    if tag_digest == target_digest:
                                        os.remove(tag_path)
                                        logger.info(f"Deleted tag {tag} pointing to digest {original_reference}")
                            except Exception as e:
                                logger.error(f"Error checking/deleting tag {tag}: {str(e)}")
        
        # 删除不再被引用的 blobs（在删除manifest文件之前）
        _delete_unreferenced_blobs(manifest_data, exclude_ref)
        
        # 删除manifest文件
        if os.path.exists(manifest_path):
            os.remove(manifest_path)
        if os.path.exists(digest_path) and digest_path != manifest_path:
            os.remove(digest_path)
        
        return '', 202
    except Exception as e:
        logger.error(f"Error deleting manifest: {str(e)}")
        return jsonify({'errors': [{'code': 'MANIFEST_INVALID'}]}), 400

# 垃圾回收
@app.route('/v2/gc', methods=['POST'])
def garbage_collection():
    try:
        # 获取所有正在使用的blobs
        used_blobs = set()
        manifest_dir = os.path.join(REGISTRY_PATH, "manifests")
        
        for repo in os.listdir(manifest_dir):
            repo_path = os.path.join(manifest_dir, repo)
            if os.path.isdir(repo_path):
                for filename in os.listdir(repo_path):
                    manifest_path = os.path.join(repo_path, filename)
                    if os.path.isfile(manifest_path):
                        try:
                            with open(manifest_path, 'rb') as f:
                                manifest_data = json.loads(f.read())
                                
                                # 添加 config blob
                                if 'config' in manifest_data and 'digest' in manifest_data['config']:
                                    used_blobs.add(manifest_data['config']['digest'].replace('sha256:', ''))
                                
                                # 添加 layers
                                if 'layers' in manifest_data:
                                    for layer in manifest_data['layers']:
                                        if 'digest' in layer:
                                            used_blobs.add(layer['digest'].replace('sha256:', ''))
                                
                                # 添加 manifests (用于 manifest lists)
                                if 'manifests' in manifest_data:
                                    for manifest in manifest_data['manifests']:
                                        if 'digest' in manifest:
                                            used_blobs.add(manifest['digest'].replace('sha256:', ''))
                        except Exception as e:
                            logger.error(f"Error processing manifest {manifest_path}: {str(e)}")
                            continue
        
        # 删除未使用的blobs
        blobs_dir = os.path.join(REGISTRY_PATH, "blobs")
        removed_blobs = []
        
        for blob in os.listdir(blobs_dir):
            if blob not in used_blobs:
                blob_path = os.path.join(blobs_dir, blob)
                if os.path.isfile(blob_path):
                    try:
                        os.remove(blob_path)
                        removed_blobs.append(blob)
                        logger.info(f"Removed unused blob: {blob}")
                    except Exception as e:
                        logger.error(f"Error removing blob {blob}: {str(e)}")
        
        # 清理uploads目录
        uploads_dir = os.path.join(REGISTRY_PATH, "uploads")
        if os.path.exists(uploads_dir):
            shutil.rmtree(uploads_dir)
            os.makedirs(uploads_dir)
            logger.info("Cleaned uploads directory")
        
        return jsonify({
            'status': 'success',
            'removed_blobs': removed_blobs
        })
    
    except Exception as e:
        logger.error(f"Error during garbage collection: {str(e)}")
        return jsonify({'errors': [{'code': 'INTERNAL_ERROR'}]}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 