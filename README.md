# Enhanced115 - 115网盘助手

> MoviePilot V2插件，基于硬链接的多线程115上传方案

[![MoviePilot](https://img.shields.io/badge/MoviePilot-v2.8.5+-green.svg)](https://github.com/jxxghp/MoviePilot)

## 🌟 核心功能

### 1. 多线程异步上传
- MoviePilot使用硬链接整理（瞬间完成）
- 插件监听事件后台异步上传115
- 3-5线程并发，效率提升80%+

### 2. 数据库同步
- 自动更新transferhistory记录
- dest_storage从local改为u115
- 兼容my_115_app等外部程序

### 3. 115分享集成
- 文件夹分享（整部电影/整季）
- 文件打包分享（多集打包）
- 自定义有效期和提取码
- 不再需要my_115_app

### 4. Telegram通知
- 分享完成自动通知

---

## 🚀 快速开始

### 第一步：配置MoviePilot

**关键配置：**
```yaml
媒体库目录：
  存储：本地（不是115！）
  路径：/media（与downloads同盘）
  
整理方式：link（硬链接）← 必须！
```

### 第二步：安装插件

```
设置 → 系统 → 插件市场
添加：https://github.com/muzinan765/Enhanced115

设置 → 插件 → 安装"Enhanced115网盘助手"
```

### 第三步：配置插件

**必需配置：**
- 115 Cookie
- 路径映射：`[{"local":"/media","remote":"/Emby"}]`

**可选配置：**
- 分享功能
- Telegram通知

---

## 📖 详细说明

查看 [plugins.v2/enhanced115/README.md](plugins.v2/enhanced115/README.md)

---

## 🔄 工作流程

```
下载完成
  ↓
MoviePilot硬链接整理（0.1秒）
  ↓ 本地：/media/电影.mkv
  ↓ 数据库：dest_storage='local'
  ↓
插件监听事件
  ↓
多线程上传115
  ↓ 115：/Emby/电影.mkv
  ↓
更新数据库
  ↓ dest_storage='u115'
  ↓
创建分享
  ↓
Telegram通知
```

---

## 📊 性能对比

| 方式 | 整理速度 | 队列阻塞 | 效率 |
|------|---------|---------|------|
| 直接上传115 | 慢 | 严重 | 基准 |
| 硬链接+插件 | ⚡ 瞬间 | ❌ 无 | +80% ✅ |

---

## ⚠️ 重要提示

1. **必须使用硬链接整理**
2. **/media和/downloads必须同盘**
3. **媒体库必须是本地存储**
4. **路径映射必须正确配置**

---

## 📄 开源协议

MIT License

---

**让MoviePilot飞起来！** 🚀
