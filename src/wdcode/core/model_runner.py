class ModelRunner:
    def __init__(self, client):
        self.client = client

    def call(self, *, messages, tools=None):
        return self.client.chat(messages, tools=tools)
