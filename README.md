# Python Docker Registry

这是一个使用 Python Flask 实现的轻量级 Docker Registry 服务器，完全兼容 Docker Registry API v2 协议。你可以使用它来搭建私有的 Docker 镜像仓库。

## 功能特点

- 完全兼容 Docker Registry API v2 协议
- 支持 Docker Push 和 Pull 操作
- 支持分块上传大文件
- 支持 manifest v1、v2 和 OCI 格式
- 支持镜像删除和垃圾回收
- 支持镜像列表和标签查询
- 本地文件系统存储
- 轻量级实现，易于部署和维护

## 系统要求

- Python 3.7+
- pip（Python 包管理器）
- 足够的磁盘空间用于存储 Docker 镜像

## 安装步骤

1. 克隆仓库：
```bash
git clone <repository-url>
cd python-docker-registry
```

2. 创建虚拟环境（推荐）：
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. 安装依赖：
```bash
pip install -r requirements.txt
```

4. 创建数据目录：
```bash
mkdir -p data/blobs data/manifests data/uploads
```

## 运行服务器

启动服务器（默认监听 5000 端口）：
```bash
python app.py
```

## 使用方法

1. 配置 Docker 客户端（如果使用 HTTP）：

在 Docker 的 daemon.json 中添加不安全仓库配置（默认位置：Linux: /etc/docker/daemon.json，Windows: %programdata%\docker\config\daemon.json）：
```json
{
  "insecure-registries": ["your-server-ip:5000"]
}
```

重启 Docker 服务：
```bash
sudo systemctl restart docker  # Linux
# 或在 Windows 中重启 Docker Desktop
```

2. 推送镜像：
```bash
# 标记镜像
docker tag your-image your-server-ip:5000/your-image

# 推送镜像
docker push your-server-ip:5000/your-image
```

3. 拉取镜像：
```bash
docker pull your-server-ip:5000/your-image
```

## API 接口

除了基本的 push 和 pull 操作外，还支持以下 API 接口：

1. 列出所有镜像仓库：
```bash
curl -X GET http://your-server-ip:5000/v2/_catalog
```

2. 列出指定镜像的所有标签：
```bash
curl -X GET http://your-server-ip:5000/v2/<name>/tags/list
```

3. 删除指定的镜像标签：
```bash
# 通过标签删除
curl -X DELETE http://your-server-ip:5000/v2/<name>/manifests/<tag>

# 通过 digest 删除
curl -X DELETE http://your-server-ip:5000/v2/<name>/manifests/sha256:<digest>
```

4. 执行垃圾回收：
```bash
curl -X POST http://your-server-ip:5000/v2/gc
```

所有 API 都支持以下查询参数：
- `n`: 限制返回结果的数量
- `last`: 分页标记，返回指定值之后的结果

## 目录结构

- `app.py` - 主程序文件
- `requirements.txt` - Python 依赖列表
- `data/` - 数据存储目录
  - `blobs/` - 存储镜像层数据
  - `manifests/` - 存储镜像清单
  - `uploads/` - 临时上传文件

## 注意事项

1. 安全性：
   - 默认使用 HTTP 协议，生产环境建议配置 HTTPS
   - 没有实现访问控制，建议在生产环境添加认证机制
   - 删除操作不可逆，请谨慎使用

2. 性能：
   - 使用本地文件系统存储，对于大规模部署可能需要考虑使用对象存储
   - 垃圾回收可能会占用较多系统资源，建议在低峰期执行

3. 限制：
   - 不支持多实例部署
   - 垃圾回收不支持并发操作

## 开发计划

- [x] 添加镜像删除功能
- [x] 实现简单的垃圾回收
- [ ] 添加 HTTPS 支持
- [ ] 实现基本的认证机制
- [ ] 添加监控指标
- [ ] 支持配置文件
- [ ] 支持分布式部署
- [ ] 添加 Web 管理界面

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License 