# 立体生成测试图片

这里有 5 张论文实验用过的左图，均为 448×256（7:4）。建议先用森林悬崖和山前角色，看前后景的相对位置和主体边缘，再用其余图片看岩石、枝叶和遮挡细节。

| 输入图 | 实验帧 | 建议观察 |
| --- | --- | --- |
| [森林悬崖](images/01-forest-cliff.png) | Spring 0037，第 34 帧 | 近处树干、悬崖和远处树林的层次 |
| [山前角色](images/02-mountain-creature.png) | Spring 0038，第 135 帧 | 前景主体与远山之间的视差，主体轮廓 |
| [前景岩石](images/03-foreground-boulder.png) | Spring 0014，第 112 帧 | 大块前景边缘、岩石纹理和背景树枝 |
| [结霜枝叶](images/04-frosted-plant.png) | Spring 0008，第 14 帧 | 前景细纹理，以及主体与虚化背景的分离 |
| [岩洞](images/05-rocky-cavern.png) | Spring 0018，第 87 帧 | 岩壁层次和局部遮挡，适合进阶检查 |

在 Agent 输入框附上一张图，发送「帮我生成右图」。对话应出现细节补偿后的右图和红青色差图，点开后可切换或下载。建议先用默认的预览尺寸。

These images are cropped and resized left frames from [Spring](https://doi.org/10.18419/darus-3376) by Lukas Mehl et al. (CVPR 2023), rendered from Blender Foundation's *Spring* assets. Both sources are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This folder contains only the inputs used for a quick workflow check.
