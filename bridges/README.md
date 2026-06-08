# Bridges — 外部桥接模块

## NapCatQQ 桥接（QQ群聊采集）— 完整部署流程

### 采集模式

QQ群采集支持**三种模式**：

| 模式 | CLI参数 | 说明 |
|------|---------|------|
| **被动监听** | `--mode listen` | WebSocket实时接收群消息（默认） |
| **主动拉取** | `--mode fetch` | HTTP API拉取历史消息 |
| **混合模式** | `--mode both` | 先拉历史，再持续监听（推荐） |

```bash
# 仅拉取历史消息（每个群200条）
python main.py collect -p qq_group --qq-groups "123456789" --mode fetch --fetch-count 200

# 仅实时监听（60分钟）
python main.py collect -p qq_group --mode listen --duration 60

# 混合模式 — 先拉历史，再持续监听（完整覆盖）
python main.py collect -p qq_group --mode both --fetch-count 300 --duration 30
```

### 架构
```
[QQ桌面端 NTQQ] ←──IPC──→ [NapCatQQ 无头客户端]
                                │
                     WebSocket (ws://localhost:3001)
                                │
                        [napcat_bridge.py]
                                │
                        [QQGroupCollector]
```

### 前置准备

**0. 注册一个新QQ号**
- 用手机号注册一个全新QQ号（不要用个人主号）
- 不绑定真实身份信息
- 仅用于被动监听，不发言

**1. 加入灰产相关QQ群**
- 打开QQ桌面客户端，用新号登录
- 在QQ搜索框中搜索以下关键词，查看群列表，加入相关群：
  ```
  刷单、接码、代实名、账号交易、解封、涨粉、数据维护
  投票、协议号、白号、企业认证、抖音推广、小红书推广
  ```
- 每个群加入后等待审核通过（通常几分钟到几小时）
- 记录群号到 `data/raw/qq_groups.json`:
  ```json
  {
    "groups": [
      {"id": "123456789", "name": "刷单手任务群", "keyword": "刷单"},
      {"id": "987654321", "name": "账号交易交流群", "keyword": "账号交易"}
    ]
  }
  ```

**2. 安装 NapCatQQ**

```powershell
# 方式A: 下载预编译版本 (推荐)
# 1. 浏览器打开 https://github.com/NapNeko/NapCatQQ/releases
# 2. 下载 Windows 版本 (如 NapCatQQ-win-x64-xxx.zip)
# 3. 解压到任意目录，例如 D:\NapCatQQ\

# 方式B: 使用 Docker
docker run -d --name napcat \
  -p 3000:3000 -p 3001:3001 \
  -v napcat_data:/app/data \
  napneko/napcatqq:latest
```

**3. 配置 NapCatQQ**

编辑 `napcat.json`（解压目录下）:
```json
{
  "general": {
    "host": "0.0.0.0",
    "port": 3000
  },
  "websocket": {
    "enable": true,
    "host": "0.0.0.0", 
    "port": 3001
  }
}
```

**4. 启动 NapCatQQ 并扫码登录**
```powershell
# Windows
cd D:\NapCatQQ
.\napcat.bat

# 首次启动会:
# 1. 启动一个本地服务器
# 2. 自动打开浏览器显示二维码
# 3. 用手机QQ扫码 → 确认登录
```

**5. 验证连接**
```powershell
# 测试 HTTP API
curl http://localhost:3000/api/get_login_info

# 预期返回: {"status":"ok","data":{"user_id":"你的QQ号","nickname":"你的昵称"}}
```

**6. 启动 BGI QQ群采集**
```bash
# 监听5分钟测试
python main.py collect -p qq_group --duration 5

# 监听指定群60分钟
python main.py collect -p qq_group --qq-groups "123456789" --duration 60
```

### 故障排查

| 问题 | 解决 |
|------|------|
| NapCatQQ启动闪退 | 检查napcat.json语法；尝试以管理员身份运行 |
| 扫码后无反应 | 刷新二维码页面；确认手机QQ与PC在同一网络 |
| ws://localhost:3001 连不上 | 确认WebSocket配置enable=true；检查端口是否被占用 |
| 群里有人说话但采集不到 | 确认群号正确；检查群消息权限 |
| QQ号被冻结 | 新号短期内不要频繁加群（一天加3-5个以内） |

### 安全注意事项

- QQ号仅用于被动监听，**绝不自动发言**
- 使用新注册的QQ号，不绑定个人信息
- NapCatQQ 使用官方 NTQQ 进程，非协议逆向
- 群消息数据仅用于情报分析，不用作其他用途
