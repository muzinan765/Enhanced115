# Enhanced115 插件说明

## 工作原理

### 基于硬链接的异步上传方案

```
MoviePilot配置：
├─ 资源目录：/downloads（local）
├─ 媒体库：/media（local，同盘）
└─ 整理方式：link（硬链接）

工作流程：
1. MoviePilot硬链接整理（0.1秒）→ 不阻塞
2. 插件监听TransferComplete事件
3. 多线程异步上传到115
4. 更新数据库（local→u115）
5. 创建115分享（可选）
6. Telegram通知（可选）
```

## 功能特性

### 1. 多线程异步上传
- 3-5个线程并发上传
- 不阻塞整理队列
- 效率提升80%+

### 2. 数据库同步
- 自动更新transferhistory
- 兼容my_115_app等外部程序
- dest_storage从local改为u115

### 3. 115分享集成
- 文件夹分享（整部电影/整季）
- 文件打包分享（多集打包）
- 自定义有效期和提取码

### 4. Telegram通知
- 分享完成自动通知
- 包含链接和提取码

## 配置说明

### 必需配置

**115 Cookies**
- 从浏览器F12→Network→复制Cookie

**上传线程数**
- 建议3-5个

**路径映射**
```json
[
  {"local": "/media", "remote": "/Emby"},
  {"local": "/media/电影", "remote": "/Emby/电影"}
]
```

### 分享配置（可选）

**115根目录ID**
- 电影根目录CID
- 电视剧根目录CID
- 从115网盘URL获取

**分享设置**
- 有效期：-1=永久，15=15天
- 提取码：4位字符或留空

### Telegram配置（可选）

- Bot Token
- Chat ID

## MoviePilot配置要求

```yaml
资源目录：
  路径：/downloads
  存储：本地

媒体库目录：
  路径：/media（与downloads同盘）
  存储：本地
  
整理方式：link（硬链接）← 关键！
```

## 依赖

```
p115client>=0.0.8
requests（Telegram通知）
```

## 版本

v2.0.0 - 完全重写，基于硬链接方案
