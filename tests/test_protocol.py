from mini_go_common.protocol import format_message, parse_command


def test_parse_fields_and_quoted_name() -> None:
    command = parse_command('REGISTER name="my bot" protocol=1')
    assert command.name == "REGISTER"
    assert command.fields["name"] == "my bot"
    assert command.fields["protocol"] == "1"


def test_format_quotes_spaces() -> None:
    line = format_message("INFO", score=12, comment="hello world")
    command = parse_command(line)
    assert command.name == "INFO"
    assert command.fields["score"] == "12"
    assert command.fields["comment"] == "hello world"
