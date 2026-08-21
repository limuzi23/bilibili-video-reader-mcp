# Output formats

## A. Default structured study notes

### 视频信息
- 标题：
- UP主：
- 链接：
- 分P：当前 / 共 N P
- 字幕来源：官方 / AI字幕 / ASR

### 一句话总结

### 核心内容
Use concise sections in the speaker's order.

### 方法与技巧
For each method:
- 方法名
- 解决什么问题
- 核心步骤
- 适用条件
- 注意事项 / 易错点
- 对应时间戳

### 关键结论

### 复习索引
A compact index of concepts → part/timestamp.

---

## B. Algorithm / machine-test / interview collection mode

For every part, without skipping:

### P{n}：{题目/章节标题}
- **题目主题**：
- **题意**：only when recoverable from the video/transcript.
- **输入输出**：only when stated or visible in source material.
- **核心方法**：
- **解题步骤**：
- **复杂度**：if stated or safely derivable.
- **易错点**：
- **视频中的代码**：verbatim only if source makes it recoverable.
- **根据讲解重写的 Python 代码**：if useful, label it clearly as reconstructed.
- **时间戳**：

After all parts:

### 合集方法索引
- 哈希 / 双指针 / 栈 / 队列 / BFS / DFS / DP / 贪心 / 二分 / 图 / 并查集 / 字符串 / 数学 ... → related P numbers

### 高频套路
Summarize repeated patterns across parts.

### 建议复习顺序
Order by prerequisite and recurrence, not arbitrary preference.

---

## C. Tutorial / practical operation mode

### 目标
### 前置条件
### 操作步骤
Numbered, preserving commands/parameters.
### 为什么这样做
### 常见错误
### 视频作者的经验性建议
### 可直接复用的命令/代码
### 时间戳索引

---

## D. Transcript-only mode

Return cleaned subtitles in chronological order:

`[00:01:23] 文本`

Remove obvious filler only if the user asks for cleaned subtitles. For verbatim transcription, preserve wording as faithfully as possible.
