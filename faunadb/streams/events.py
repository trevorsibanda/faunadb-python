
from faunadb._json import parse_json_or_none
from faunadb.errors import BadRequest, PermissionDenied


def parse_stream_request_result_or_none(request_result):
    """
    Parses a stream RequestResult into a stream Event type.
    """
    event = None
    parsed = request_result.response_content
    if parsed is None:
        return UnknownEvent(request_result)
    evt_type = parsed.get('event', None)
    if evt_type == "start":
        event = Start(parsed)
    elif evt_type is None and 'errors' in parsed:
        evt_type = 'error'
        event = Error(BadRequest(request_result))
    elif evt_type == 'error':
        event = Error(parsed)
    elif evt_type == 'version':
        event = Version(parsed)
    elif evt_type == 'history_rewrite':
        event = HistoryRewrite(parsed)
    else:
        event = UnknownEvent(request_result)

    return event


class Event(object):
    """
    A stream event.
    """
    def __init__(self, event):
        self.event = event

class ProtocolEvent(Event):
    """
    Stream protocol event.
    """
    def __init__(self, event):
        super().__init__(event)


class Start(ProtocolEvent):
    """
    Stream's start event. A stream subscription always begins with a start event.
    Upcoming events are guaranteed to have transaction timestamps equal to or greater than
    the stream's start timestamp.

    :param data: Data
    :param txnTS: Timestamp
    """
    def __init__(self, parsed):
        super().__init__('start')
        self.data = parsed['data']
        self.txnTS = parsed['txnTS']

    def __repr__(self):
        return "stream:event:Start(data=%s, txnTS=%d)"%(self.data, self.txnTS)

class Error(ProtocolEvent):
    """
    An error event is fired both for client and server errors that may occur as
    a result of a subscription.
    """
    def __init__(self, parsed):
        super().__init__('error')
        self.error = None
        self.code = None
        self.description = None
        if isinstance(parsed, dict):
            if 'data' in parsed:
                self.error = parsed['data']
                if isinstance(parsed['data'], dict):
                    self.code = parsed['data'].get('code', None)
                    self.description = parsed['data'].get('description', None)
            elif 'errors' in parsed:
                self.error = parsed['errors']
            else:
                self.error = parsed
        else:
            self.error = parsed

    def __repr__(self):
        return "stream:event:Error(%s)"%(self.error)

class HistoryRewrite(Event):
    """
    A history rewrite event occurs upon any modifications to the history of the
    subscribed document.

    :param data:  Data
    :param txnTS: Timestamp
    """
    def __init__(self, parsed):
        super().__init__('history_rewrite')
        if isinstance(parsed, dict):
            self.data = parsed.get('data', None)
            self.txnTS = parsed.get('txnTS')

        def __repr__(self):
            return "stream:event:HistoryRewrite(data=%s, txnTS=%s)" % (self.data, self.txnTS)

class Version(Event):
    """
    A version event occurs upon any modifications to the current state of the
    subscribed document.

    :param data:  Data
    :param txnTS: Timestamp
    """
    def __init__(self, parsed):
        super().__init__('version')
        if isinstance(parsed, dict):
            self.data = parsed.get('data', None)
            self.txnTS = parsed.get('txnTS')

    def __repr__(self):
        return "stream:event:Version(data=%s, txnTS=%s)" % (self.data, self.txnTS)


class UnknownEvent(Event):
    """
    Unknown stream event.
    """
    def __init__(self, parsed):
        super().__init__(None)
        self.event = 'unknown'
        self.data = parsed

