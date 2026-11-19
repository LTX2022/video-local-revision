# 视频局部修订

面向已有视频的局部修订 Skill。根据原片、参考素材和时间要求，协助处理灯光、标识、立体部件或屏幕内容的定点修改。屏幕可整块换画，也可只换手机画面上的文字、数字或图标，同时保留原界面和随镜头变化的反光。

实际制作方法取决于素材、可用软件和任务要求。本 Skill 提供工作方法、案例和技术检查工具，不是一键自动完成视频修复的软件；长镜头、强运动模糊、频繁遮挡或复杂材质的效果需要针对具体素材验证。

## 安装

将本仓库克隆或下载到本地，在仓库根目录执行以下命令，安装到用户级 Skill 目录：

```sh
mkdir -p "$HOME/.agents/skills"
mkdir "$HOME/.agents/skills/video-local-revision" && \
  cp -R video-local-revision/. "$HOME/.agents/skills/video-local-revision/"
```

如果目标目录已存在，第二条命令会报错；请先检查已有内容，避免覆盖。也可以直接把仓库中的 `video-local-revision` 目录作为 Skill 文件夹交给能访问本地文件的 AI，要求其读取 `SKILL.md`。

## 使用

在支持 Skill 的环境中明确调用 `$video-local-revision`，例如：

> $video-local-revision 请根据 `/素材/原片.mov` 和 `/素材/屏幕参考.png`，替换 00:02–00:05 的电视画面，保留原镜头运动和音轨，输出与原片规格一致的视频。先检查现有素材，制作后检查画面连续性并说明验收结果。

只换屏幕里的数字时，可以这样划定范围：“按参考图替换红框内两行数字，保留折线、时间刻度、反光和原声。对照原片检查手机转动时有没有滑动，以及修改段前后是否自然衔接。”

按任务提供原片、参考图或替换内容、修改位置和时间段、动作或声音节点、应保留内容及输出规格。若有可编辑工程、干净底片或已确认版本，也可一并提供。实际制作可能需要视频编辑、合成、三维或代码工具，具体取决于选择的方法。

## 技术检查

`scripts/media_check.py` 只读取视频并在终端输出 JSON，检查规格、帧数、流信息及可选的完整解码；不修改视频，也不制作替换画面。需要 Python 3、PATH 中的 `ffprobe`；使用 `--decode` 时还需要 `ffmpeg`。Python 脚本无需额外 pip 依赖。

从仓库根目录运行下面的命令。

```sh
cd video-local-revision

# 检查成片
python3 scripts/media_check.py inspect "/素材/成片.mov"

# 比较原片与成片，并检查完整解码
python3 scripts/media_check.py compare "/素材/原片.mov" "/素材/成片.mov" --decode --timeout 300

# 按明确约定检查 1080p 预览
python3 scripts/media_check.py compare "/素材/原片.mov" "/素材/预览.mp4" --size 1920x1080 --video-codec h264

# 使用包内示例检查工具环境
python3 scripts/media_check.py inspect examples/pv5-screen-before-after.mp4 --decode --timeout 30
```

对原片和成片执行 `compare` 后，可查看 `technical_match` 和逐项 `findings`。默认核对源规格，包括声道数与采样率。指定尺寸、编码或音频目标时，按目标比较对应字段。详细选项见[工具用法](video-local-revision/references/tools.md)。

需要查具体一帧时，可用[局部对照工具](video-local-revision/references/tools.md#局部对照)输出原速并排视频、原尺寸截图和帧号表。输入原片或上次确认版，以及需要核对的新成片。

技术检查通过不等于视觉验收。画面贴合、遮挡、闪烁和整体连续性需要实际查看视频；未观看或未检查的项目应明确说明。

## 历史案例

`examples/` 包含三段左右对照短片，分别展示车灯、电子后视镜和电视画面修改。它们经过缩小和重新编码，用于理解观察重点，不能替代原分辨率成片验收，也不能证明其他素材或模型的效果。见[案例阅读说明](video-local-revision/examples/阅读说明.md)。

[PV4 手机数字案例](video-local-revision/references/pv4-phone-digits.md)以文字说明少量元素替换、强反光下的局部跟踪与帧间复核；可从[屏幕制作专题](video-local-revision/references/screen-replacement.md)直接选用适合当前素材的做法。

[手机屏幕练习](video-local-revision/examples/phone-practice/任务.md)包含一段原创原片、替换参考和明确的制作要求，可作为更换模型或工具时的同题验证。

## 目录结构

```text
.
├── README.md
├── 使用说明.md
└── video-local-revision/
    ├── SKILL.md                 # Skill 入口
    ├── agents/                  # 环境配置
    ├── references/              # 专题、验收和工具用法
    ├── scripts/                 # 技术检查及局部对照
    └── examples/                # 历史对照短片及手机练习
```
