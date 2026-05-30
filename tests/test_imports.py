def test_core_packages_import_without_api_key():
    import wdcode
    import wdcode.core.agent_loop
    import wdcode.core.tool_loop
    import wdcode.infra.config
    import wdcode.security.paths
    import wdcode.tools

    assert wdcode is not None
