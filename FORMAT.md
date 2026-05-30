# Ink 编写指南

> ErisPulse-CYOA 使用 [Ink](https://www.inklestudios.com/ink) 作为故事格式。

---

## 什么是 Ink

Ink 是 Inkle Studios 开发的互动叙事标记语言。语法简洁、功能完备。

**工具链:**
- [Inky](https://github.com/inkle/inky) — 编辑器，自带编译
- [inklecate](https://github.com/inkle/ink) — 命令行编译器
- [inkpython](https://pypi.org/project/inkpython/) — Python 运行时

---

## 基础语法

### Knot（节点）

```ink
=== start
你站在十字路口。
* 向左走 -> left
* 向右走 -> right

=== left
你发现了一座宝藏！
-> DONE

=== right
一条死路...
-> DONE
```

### 选项

```ink
* 普通选项 -> target
+ 粘性选项（重复出现） -> target
* [条件选项] 文本 -> target
```

### 跳转

```ink
-> target        # 跳转到 knot
-> DONE          # 结束故事
->               # 跳转到下一个选项（fallthrough）
```

### 变量

```ink
VAR gold = 0
~gold += 10
你目前有 {gold} 枚金币。
```

### 条件

```ink
{ gold >= 50:
    你有足够金币！
    -> rich_ending
}
* 购买武器 { gold >= 30 } -> buy_weapon
```

### Knot vs Stitch

```ink
=== forest
= enter
你进入森林...
-> explore
= explore
你四处探索...
-> DONE
```

跳转：`-> forest.enter`

---

## 高级特性

### 循环

```ink
VAR count = 0
- (loop)
  第 {count + 1} 次尝试
  ~count++
  { count < 5: -> loop }
  -> DONE
```

### 函数

```ink
=== function add(x, y)
~return x + y

~temp add(3, 5)
结果是 {temp}。
```

### 隧道

```ink
-> tunnel ->
* 隧道中的选择...
-> end

=== tunnel
你进入隧道...
->->
=== end
你走出隧道...
-> DONE
```

### 洗牌/随机

```ink
"{~A|B|C}"          # 随机选一个
"{!A|B|C}"          # 无放回选一个（遍历）
"{~}"               # 随机数
```

---

## 元数据标签

Ink 的 `#` 标签可用于向引擎传递元数据：

```ink
# image: https://example.com/bg.png
# author: Star
```

支持的标签：
- `# image: <URL>` — 节点图片
- `# author: <Name>` — 作者（仅第一个 knot 的标签生效）

---

## 编译与导入

### 用 Inky 编译

1. 打开 `.ink` 文件
2. File → Export as JSON
3. 得到 `.ink.json` 文件

### 用 inklecate 编译

```bash
inklecate -o story.ink.json story.ink
```

### 导入到 CYOA

直接导入编译后的 `.ink.json`：

```
/cyoa import https://example.com/story.ink.json
```

或放入仓库的 `stories/<id>/story.ink.json`。

---

## 完整示例

```ink
# author: ErisPulse
# image: https://example.com/dragon.png

VAR hp = 100
-> start

=== start
你站在古老龙塔前。
* 进入塔内 -> hall
* 离开 -> leave

=== hall
昏暗的大厅。HP: {hp}。
* 继续前进 -> fight
* 转身离开 -> leave

=== fight
哥布林出现！
~ hp -= 10
你击退了哥布林，但受了伤。HP: {hp}
{ hp > 50:
    你还撑得住。
    -> victory
- else:
    你伤得太重了...
    -> death
}

=== victory
你成功穿过龙塔！
-> DONE

=== leave
你转身离开，龙塔的传说将继续流传。
-> DONE

=== death
你倒在了塔中。
-> DONE
```

---

## 限制

- 需用 Inky/inklecate 编译为 `.ink.json` 后导入
- 引擎不处理自定义逻辑 — 所有分支和变量都在 Ink 中完成
- 图片通过 `# image:` 标签标记
