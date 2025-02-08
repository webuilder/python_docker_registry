# Python Docker Registry

这是一个使用 Python 实现的 Docker Registry v2 服务器。

## 功能特点

- 完全兼容 Docker Registry API v2
- 支持 docker push 和 docker pull 命令
- 镜像存储在本地 data/ 目录中
- 默认监听 5000 端口

## 使用方法

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 启动服务器：
```bash
python app.py
```

3. 使用 Docker 命令推送镜像：
```bash
# 标记镜像
docker tag your-image localhost:5000/your-image

# 推送镜像
docker push localhost:5000/your-image
```

4. 使用 Docker 命令拉取镜像：
```bash
docker pull localhost:5000/your-image
```

## 注意事项

- 确保 5000 端口未被其他服务占用
- 确保 data/ 目录具有适当的读写权限 