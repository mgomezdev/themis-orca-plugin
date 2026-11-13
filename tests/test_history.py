from types import SimpleNamespace

from themis_orca.history import capture_key, save_record, source_key


def test_history_identity_separates_servers_and_plates_and_never_exposes_paths():
    path = "C:/private/projects/batch.3mf"
    first = source_key("https://one/api/v1",path,1,1)
    assert first == source_key("https://one/api/v1",path,999,1)
    assert first != source_key("https://two/api/v1",path,1,1)
    assert first != source_key("https://one/api/v1",path,1,2)
    assert "private" not in first and len(first) == 64


def test_gcode_identity_uses_content_and_export_profile_independently_of_capture_token():
    row = SimpleNamespace(digest="hash",profile="Machine")
    assert capture_key("https://one/api/v1",row) == capture_key("https://one/api/v1",row)
    row.profile = "Different"
    assert capture_key("https://one/api/v1",row) != capture_key("https://one/api/v1",SimpleNamespace(digest="hash",profile="Machine"))


def test_history_is_bounded_and_preserves_the_host_configuration():
    config = {"url":"https://themis/api/v1","api_key":"private-key","future_option":True}
    for index in range(105):
        save_record(config,str(index),{"send_id":str(index)})
    assert len(config["send_history"]) == 100 and "0" not in config["send_history"]
    assert config["api_key"] == "private-key" and config["future_option"] is True
