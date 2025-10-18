from cogs.message_reader import MessageReaderCog


class DummyAttachment:
    def __init__(self, filename, content_type=None, description=""):
        self.filename = filename
        self.content_type = content_type
        self.description = description


def test_summarize_single_image_attachment():
    attachments = [DummyAttachment("photo.png", "image/png")]
    summary = MessageReaderCog._summarize_attachments(attachments)
    assert summary == "ファイル"


def test_summarize_multiple_attachments_with_overflow():
    attachments = [
        DummyAttachment("a.png", "image/png"),
        DummyAttachment("b.mp4", "video/mp4"),
        DummyAttachment("c.txt", "text/plain"),
        DummyAttachment("d.pdf", "application/pdf"),
    ]
    summary = MessageReaderCog._summarize_attachments(attachments)
    assert summary == "ファイル"
