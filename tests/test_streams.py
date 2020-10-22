from __future__ import division
from datetime import date, datetime
from time import sleep, time

from faunadb.errors import BadRequest, NotFound, FaunaError
from faunadb.objects import FaunaTime,  Ref, SetRef, _Expr, Native, Query
from faunadb import query
from faunadb.streams import Connection, Subscription, EventDispatcher
from tests.helpers import FaunaTestCase

def _on_unhandled_error(event):
    if hasattr(event, "data") and isinstance(event.data, Exception):
        raise event.data
    else:
        raise Exception(event)

class StreamTest(FaunaTestCase):
    @classmethod
    def setUpClass(cls):
        super(StreamTest, cls).setUpClass()
        cls.collection_ref = cls._q(query.create_collection({"name":"stream_test_coll"}))["ref"]

    #region Helpers

    @classmethod
    def _create(cls, n=0, **data):
        data["n"] = n
        return cls._q(query.create(cls.collection_ref, {"data": data}))

    @classmethod
    def _q(cls, query_json):
        return cls.client.query(query_json)

    @classmethod
    def stream_sync(cls, expression, options=None, **args):
        if "on_error" not in args:
            args["on_error"] = _on_unhandled_error
        return cls.client.stream(expression, options, **args)

    @classmethod
    def stream_async(cls, expression, options=None, **args):
        if "on_error" not in args:
            args["on_error"] = _on_unhandled_error
        return cls.client.stream(expression, options, blocking=False, **args)

    #endregion

    def test_stream_on_document_reference(self):
        ref = self._create(None)["ref"]
        stream = None

        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(isinstance(event.data, FaunaTime))
            stream.close()

        stream = self.stream_sync(ref, None, on_start=on_start)
        stream.start()

    def test_stream_reject_non_readonly_query(self):
        q = query.create_collection({"name": "c"})
        stream = None
        def on_error(error):
            self.assertEqual(error.event, 'error')
            self.assertTrue(isinstance(error.error, BadRequest))
            self.assertEqual(error.error._get_description(),
                              'Write effect in read-only query expression.')
            stream.close()
        stream= self.stream_sync(q, on_error=on_error)
        stream.start()

    def test_stream_select_fields(self):
        ref = self._create()["ref"]
        stream = None
        fields = {"new", "diff"}
        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(isinstance(event.data, FaunaTime))
            self._q(query.update(ref, {"data":{"k": "v"}}))
        
        def on_version(event):
            self.assertEqual(event.event, 'version')
            self.assertTrue(isinstance(event.data, dict))
            self.assertTrue(isinstance(event.txnTS, int))
            keys = set(event.data.keys())
            self.assertEqual(keys, {"new", "diff"})
            stream.close()
        options = {"fields": list(fields)}
        stream = self.stream_sync(ref, options=options, on_start=on_start, on_version=on_version)
        stream.start()


    def test_stream_update_last_txn_time(self):
        ref = self._create()["ref"]
        last_txn_time = self.client.get_last_txn_time()
        stream = None

        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(self.client.get_last_txn_time() > last_txn_time)
            #for start event, last_txn_time maybe be updated to response X-Txn-Time header
            # or event.txnTS. What is guaranteed is the most recent is used- hence >=.
            self.assertTrue(self.client.get_last_txn_time() >= event.txnTS)
            self._q(query.update(ref, {"data": {"k": "v"}}))

        def on_version(event):
            self.assertEqual(event.event, 'version')
            self.assertEqual(event.txnTS, self.client.get_last_txn_time())
            stream.close()

        stream = self.stream_sync(ref, on_start=on_start, on_version=on_version)
        stream.start()

    def test_stream_handle_request_failures(self):
        stream=None
        def on_error(event):
            self.assertEqual(event.event, 'error')
            self.assertTrue(isinstance(event.error, BadRequest))
            self.assertEqual(event.error._get_description(),
                             'Expected a Ref or Version, got String.')
        stream=self.stream_sync('invalid stream', on_error=on_error )
        stream.start()

    def test_start_active_stream(self):
        ref = self._create(None)["ref"]
        stream = None

        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(isinstance(event.data, FaunaTime))
            self.assertRaises(FaunaError, lambda: stream.start())
            stream.close()

        stream = self.stream_sync(ref, None, on_start=on_start)
        stream.start()


    def test_stream_auth_revalidation(self):
        ref = self._create()["ref"]
        stream = None

        server_key = self.root_client.query(
            query.create_key({"database": self.db_ref, "role": "server"}))
        client = self.root_client.new_session_client(
            secret=server_key["secret"])

        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(isinstance(event.data, FaunaTime))
            self.root_client.query(query.delete(server_key["ref"]))
            self.client.query(query.update(ref, {"data": {"k": "v"}}))

        def on_error(event):
            self.assertEqual(event.event, 'error')
            self.assertEqual(event.code, 'permission denied')
            self.assertEqual(event.description,
                             'Authorization lost during stream evaluation.')
            stream.close()


        stream = client.stream(ref, blocking=False, on_start=on_start, on_error=on_error)
        stream.start()
        stream._join_async_thread()

    def test_async_streams(self):
        ref = self._create()["ref"]
        stream = None
        count = 10+ int(time()%60)

        def on_start(event):
            self.assertEqual(event.event, 'start')
            self.assertTrue(isinstance(event.data, FaunaTime))
            for i in range(count):
                self._q(query.update(ref, {"data": {"k": i}}))

        def on_version(event):
            self.assertEqual(event.event, 'version')
            self.assertTrue(isinstance(event.data, dict))
            self.assertTrue(isinstance(event.txnTS, int))
            if event.data['new']['data']['k'] == count-1:
                stream.close()

        stream = self.client.stream(ref, blocking=False, on_start=on_start, on_version=on_version, on_error=on_version)
        stream.start()
        stream._join_async_thread()
