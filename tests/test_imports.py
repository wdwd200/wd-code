def test_core_packages_import_without_api_key():
    import wdcode
    import wdcode.core.agent_loop
    import wdcode.core.tool_loop
    import wdcode.eval
    import wdcode.infra.config
    import wdcode.security.paths
    from wdcode.core.failure_recovery import FailureEvent, FailureReport, RetryPolicy
    from wdcode.eval.tasks import EvalResult, EvalTask, run_eval_task
    from wdcode.session import (
        CheckpointStore,
        CompressionPolicy,
        ConversationCompression,
        TurnCheckpoint,
    )
    from wdcode.validation.discovery import ValidationPlan, discover_validation_plan
    from wdcode.validation.loop import (
        RepairRequest,
        ValidationLoopPolicy,
        ValidationLoopReport,
        run_validation_loop,
    )
    import wdcode.tools

    assert wdcode is not None
    assert wdcode.eval is not None
    assert RetryPolicy is not None
    assert FailureEvent is not None
    assert FailureReport is not None
    assert CheckpointStore is not None
    assert CompressionPolicy is not None
    assert ConversationCompression is not None
    assert TurnCheckpoint is not None
    assert EvalTask is not None
    assert EvalResult is not None
    assert run_eval_task is not None
    assert ValidationPlan is not None
    assert discover_validation_plan is not None
    assert ValidationLoopPolicy is not None
    assert ValidationLoopReport is not None
    assert RepairRequest is not None
    assert run_validation_loop is not None
