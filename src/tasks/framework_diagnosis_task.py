from ok import DiagnosisTask


class FrameworkDiagnosisTask(DiagnosisTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = '框架诊断'
        self.description = '收集截图设备与系统环境信息，用于排查捕获和运行问题'
        self.visible = False
        self.debug_tool = True
