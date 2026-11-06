实况照片备份查看器 V1.2 — 验收构建目录（2026-10-28）
====================================================

【这是什么】
用当前 V1.2 源码构建出的独立 EXE 及其构建/验收证据。
本目录是验收候选物，尚未替换 dist 目录内的「实况照片备份查看器.exe」（正式版仍为 V1.0 构建物）。

【两个 EXE】
- 实况照片备份查看器_V1.2.exe      主交付物：GUI 版（无控制台窗口，与 V1.0 同形态）
- 实况照片备份查看器_V1.2_cli.exe  控制台版：CLI 取证与脚本化使用
两者来自同一份源码、同一套构建配置，仅 bootloader 子系统不同。

【SHA-256】
- 实况照片备份查看器_V1.2.exe       F7257D447957B082950671A0FF86C49C44E615021576CC11CA174711F51801E5  (41,878,941 B)
- 实况照片备份查看器_V1.2_cli.exe   41DCD0B4792AFA6D088FB6EE1C66BD71621009F69F39A7A297AA0DAEE7B92F23  (41,875,785 B)
- 对应源码 LivePhoto_Backup.pyw    529C8FEC1F86811EDAD9EC313503A635FD2A80F861054D1FB379C56A3B5705C1

【目录说明】
- logs/            完整构建日志（窗口版 / 控制台版）
- spec/            自动生成的 .spec 配置，可原样复现构建
- 验收记录/         测试结果 JSON、运行日志、16 张界面状态截图
- build_work*      PyInstaller 中间目录（可随时删除）

【构建命令】
  .venv-build/Scripts/python.exe -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "实况照片备份查看器_V1.2" --collect-all imageio_ffmpeg ^
    --distpath "./发布构建/验收构建_V1.2" --workpath "./发布构建/验收构建_V1.2/build_work" ^
    --specpath "./发布构建/验收构建_V1.2/spec" --log-level INFO "./LivePhoto_Backup.pyw"

【完整报告】
项目根目录 文档/ 实况照片备份查看器-V1.2 实现与交付报告.md

【注意】
- 本目录内容未经授权不得替换 dist 目录内现有 EXE 或对外发布。
- 真实 iPhone HEVC / .mov 样本尚未验证，暂不得宣称兼容。