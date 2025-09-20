## 原项目：https://github.com/xLmiler/grok2api_python

## 安装步骤

### 方法1：Docker部署
```bash
git clone https://github.com/TXT2GAM/grok2api_python.git
cd grok2api_python

docker build -t grok2api .

docker run -d -p 3003:5200 grok2api
```

---

### 方法2：Docker Compose部署

```bash
git clone https://github.com/TXT2GAM/grok2api_python.git
cd grok2api_python

# 编辑 docker-compose.yml 中的环境变量
# 默认映射到 3003 端口
# nano docker-compose.yml

docker compose up -d
```

#### 更新容器

```bash
cd grok2api_python

git pull origin main
# or
# git fetch origin && git reset --hard origin/main

docker compose down
docker compose build --no-cache
docker compose up -d
```

---

### 支持模型

`grok-3`, `grok-4`, `grok-4-fast`


---

### 前端管理

http://localhost:3003/manager