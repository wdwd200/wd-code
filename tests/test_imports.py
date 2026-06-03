def test_core_packages_import_without_api_key():
    import wdcode
    import wdcode.core.agent_loop
    import wdcode.core.tool_loop
    import wdcode.infra.config
    import wdcode.security.paths
    from wdcode.core.failure_recovery import FailureEvent, FailureReport, RetryPolicy
    from wdcode.session import CheckpointStore, TurnCheckpoint
    import wdcode.tools

    assert wdcode is not None
    assert RetryPolicy is not None
    assert FailureEvent is not None
    assert FailureReport is not None
    assert CheckpointStore is not None
    assert TurnCheckpoint is not None
