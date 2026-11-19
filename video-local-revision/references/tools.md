# 技术检查与局部对照

工具：`scripts/media_check.py`。仅读取本地输入，JSON 输出到终端；不覆盖原片，不生成替换画面。它帮助核对技术事实，不能判断透视、贴合、闪烁或美术质量。

## 环境与运行

需要 Python 3 和可在 PATH 中找到的 `ffprobe`。使用 `--decode` 时还需要 `ffmpeg`。Python 部分仅用标准库，无需 pip 安装依赖。工具缺失时先检查已有安装；不要把依赖报错描述成素材损坏。

以下命令在 `video-local-revision` 文件夹内执行。含空格的路径要加引号。

```sh
# 检查一份文件：实际扫描视频帧数，并读取流信息
python3 scripts/media_check.py inspect "/绝对路径/成片.mov"

# 对照原片与成片，按“规格应保持一致”的基准列出差异
python3 scripts/media_check.py compare "/绝对路径/原片.mov" "/绝对路径/成片.mov"

# 按约定检查预览的尺寸和编码
python3 scripts/media_check.py compare "/绝对路径/原片.mov" "/绝对路径/预览.mp4" --size 1920x1080 --video-codec h264

# 加做全部音视频流的完整解码检查，不重新编码
python3 scripts/media_check.py compare "/绝对路径/原片.mov" "/绝对路径/成片.mov" --decode --timeout 300
```

`--timeout` 是每一次外部工具调用的最长秒数，默认 300；一次 compare 可包含多次调用。扫描帧数也会读取整段媒体，长文件先估算成本。普通修改不需要对所有历史版本重复扫描。

## 读懂结果

| 字段 | 含义 |
| --- | --- |
| `video_streams` / `audio_streams` | 读取到的流及其属性；附带封面不作为可播放视频流 |
| `counted_frames` | ffprobe 实际扫描得到的帧数，不只相信文件声明的帧数 |
| `comparisons` | compare 模式的逐项对照，包括规格、帧数、流数和时长 |
| `technical_match` | compare 的已检查项目是否符合原片或显式目标。true 为符合，false 为差异或错误，null 为证据不足。正常的 inspect 返回 null |
| `findings` | `mismatch` 为规格差异，`unknown` 为证据不足，`error` 为探测或解码问题 |
| `decode.status` | passed 已完整解码、failed 检查失败、not_requested 未执行额外完整解码 |
| `visual_review` | 始终为 required，提示还需要实际画面检查 |

返回码 0 表示工具完成检查，**不表示所有比较一致**；需要读 findings 和 technical_match。返回码 1 表示报告中有探测警告或解码错误；返回码 2 表示输入、工具、探测执行或参数问题。出现失败应先读 JSON 错误信息；参数错误由命令行帮助解释。

默认对照包含声道数和采样率。`--size`、`--video-codec`、`--audio-codec`、`--audio-channels` 和 `--audio-sample-rate` 可各自指定交付目标，适用于对应类型的各条流。未指定的已检查字段仍以原片为基准。编码名称使用 ffprobe 的 `codec_name`。对有意改变帧率、时长或流数量的交付，按用户要求分别解读这些差异。

## 比较边界

- 视频时长容差为一个原片元数据帧间隔；音频时长按一个源音频采样的容差比较。AAC 编码补齐可能造成差异，需要结合导出要求和实际同步判断。
- 平均帧率与名义帧率不同会提示可能存在 VFR 或不规则时序；二者相同也不能证明每帧时间间隔一致。逐帧时间戳未验证。
- 音轨数量和时长相同不证明声音内容、响度或同步相同。脚本不做声音内容对比。
- 多音轨按流顺序配对；缺失流时长不会用容器总时长冒充该流时长。
- 不比较图像内容、色彩解释、HDR 元数据、像素格式或压缩质量；有这些交付要求时另行核对。

## 局部对照

`scripts/compare_region.py` 使用 Python 3、ffprobe 和带 libx264 的 ffmpeg，读取两个同尺寸版本。左侧可选原片或上次确认版，右侧放本次成片。对照原片检查贴合、运动和光影，对照上次确认版检查已认可的区域与帧段。两份输入应对齐到同一个剪辑起点。脚本按各自第一帧归零后的逐帧显示时间和帧序校验，同一时点若对不上会报错。

```sh
python3 scripts/compare_region.py "/绝对路径/原片.mov" "/绝对路径/成片.mov" --start 2 --end 3 --roi 240,120,320,180 --out "/临时目录/局部对照"
```

输出目录须为新目录，父目录须已存在。`--start` 含起点，`--end` 不含终点，单位为秒。`--roi` 用解码画面的左上角 x、y、宽、高，省略时取整帧。对于带旋转元数据的视频，坐标以编码方向为准。`--frame` 是从第一帧开始的零基帧号，缺省为区间内首帧。工具扫描完整视频的帧时间，长文件按需要使用。

- `review.mp4` 用于原速、静音并排查看，时间从选段开始。需要核对音效时同时回看有声母版。
- `frame.png` 为指定帧的原尺寸并排截图。位置和边界可直接核对，精确色彩仍以正确解读的母版为准。
- `frames.tsv` 对应预览帧号、输入帧号、源片秒数和截图标记。找到跳动后可用该表定位，再指定具体帧生成截图。
