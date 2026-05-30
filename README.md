# ErisPulse-CYOA

**CYOA**（Choose Your Own Adventure，选择你自己的旅途）— 基于 [inkpython](https://pypi.org/project/inkpython/) 的多平台 Ink 互动小说播放器。

## 特性

- **Ink 原生格式** — 用 [Ink](https://www.inklestudios.com/ink) 编写，Inky/inklecate 编译
- **跨平台按钮** — Telegram / 云湖 / QQBot 按钮 + `event.choose()` 回退
- **仓库分发** — 添加 Git 仓库自动获取故事
- **独立存档** — 每用户每故事多槽位
- **图片支持** — `# image:` 标签

## 安装

```bash
epsdk install CYOA
```

## 命令

```
/cyoa                        帮助
/cyoa list                   故事列表
/cyoa play <ID>              开始
/cyoa import <URL>           导入 .ink.json
/cyoa save|load|restart|quit 游戏管理
/cyoa repo list|add|remove|update  仓库管理
```

## 快速开始

导入编译好的 `.ink.json` 直接玩：

```
/cyoa import https://example.com/my_story.ink.json
/cyoa play my_story
```

或添加小说仓库，一次更新就能获取全部故事：

```
/cyoa repo add <名称> https://raw.githubusercontent.com/<用户>/<仓库>/main
/cyoa repo update
/cyoa list
/cyoa play <故事ID>
```

## 推荐仓库

我们维护的官方故事合集：

```
/cyoa repo add official https://raw.githubusercontent.com/wsu2059q/cyoa-stories/main
```

贡献请 Fork [cyoa-stories](https://github.com/wsu2059q/cyoa-stories)。

## 编写故事

用 [Inky](https://github.com/inkle/inky) 编写 `.ink` 文件，导出为 `.ink.json` 后导入。

详见 **[FORMAT.md](FORMAT.md)**。

## 平台兼容

| 平台 | 交互 |
|------|------|
| Telegram | Inline Keyboard |
| 云湖 | Buttons (actionType=3) |
| QQBot | Keyboard |
| 其他 | `event.choose()` |

## License

MIT
