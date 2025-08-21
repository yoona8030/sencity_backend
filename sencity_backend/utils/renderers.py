from rest_framework.renderers import JSONRenderer

class UTF8JSONRenderer(JSONRenderer):
    """
    JSONRenderer with UTF-8 encoding (ensure_ascii=False)
    """
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return super().render(
            data,
            accepted_media_type,
            renderer_context,
        ).decode("utf-8").encode("utf-8")