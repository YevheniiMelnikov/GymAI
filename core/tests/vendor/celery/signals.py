import types


class _Sig:
    def connect(self, *args, **kwargs):
        return None


signals = types.SimpleNamespace(task_prerun=_Sig(), task_postrun=_Sig(), task_failure=_Sig(), task_success=_Sig())
