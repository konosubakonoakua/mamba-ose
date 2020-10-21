from typing import List
from functools import wraps
from collections import namedtuple
from abc import ABC

import Ice
import IcePy
from MambaICE.Dashboard import DataRouter, DataRouterRecv, DataClient, UnauthorizedError
from utils.data_utils import DataDescriptor, TypedDataFrame
from mamba_server.session_manager import set_connection_closed_callback

import mamba_server

client_verify = mamba_server.verify

Client = namedtuple("Client", ["is_remote", "prx", "callback"])
# is_remote: bool, specify the client is Remote or Local.
# prx: DataClientPrx, for remote client.
# callback: DataClientCallback, if the client is local, this is the callback
#  interface to invoke.


class DataClientCallback(ABC):
    def scan_start(self, _id, data_descriptors):
        raise NotImplementedError

    def data_update(self, frames):
        raise NotImplementedError

    def scan_end(self, status):
        raise NotImplementedError


class DataProcessor(ABC):
    def process_data_descriptors(self, _id, keys: List[DataDescriptor])\
            -> List[DataDescriptor]:
        raise NotImplementedError

    def process_data(self, frames: List[TypedDataFrame])\
            -> List[TypedDataFrame]:
        raise NotImplementedError


class DataRouterRecvI(DataRouterRecv):
    def __init__(self, data_router):
        self.data_router = data_router

    def scanStart(self, _id, keys, current=None):
        self.data_router.logger.info(f"Scan start received, scan id {_id}")
        self.data_router.scan_id = _id

        for dp in self.data_router.data_process_chain:
            assert isinstance(dp, DataProcessor)
            keys = dp.process_data_descriptors(_id, keys)

        # forward data
        for client in self.data_router.clients:
            to_send = []
            for key in keys:
                self.data_router.keys[key.name] = key
                if client not in self.data_router.subscription:
                    continue
                if key.name in self.data_router.subscription[client] or \
                        ("*" in self.data_router.subscription[client] and
                         not key.name.startswith("__")):
                    to_send.append(key)
            try:
                self.data_router.logger.info(f"Forward data descriptors to {client}")
                if client.is_remote:
                    client.prx.scanStart(self.data_router.scan_id, to_send)
                else:
                    client.callback.scan_start(self.data_router.scan_id, to_send)
            except Ice.ConnectionLostException:
                self.data_router._connection_closed_callback(current.con)
                pass

    def pushData(self, frames, current=None):
        for dp in self.data_router.data_process_chain:
            assert isinstance(dp, DataProcessor)
            frames = dp.process_data(frames)

        for client in self.data_router.clients:
            to_send = []
            for frame in frames:
                key = frame.name
                if key in self.data_router.subscription[client] or \
                        ("*" in self.data_router.subscription[client] and
                         not key.startswith("__")):
                    to_send.append(frame)
            if to_send:
                try:
                    self.data_router.logger.info(f"Forward data frames {frames} to {client}")
                    if client.is_remote:
                        client.prx.dataUpdate(to_send)
                    else:
                        client.callback.data_update(to_send)
                except (Ice.ConnectionLostException):
                    self.data_router._connection_closed_callback(current.con)

    def scanEnd(self, status, current):
        self.data_router.logger.info(f"Scan end received")
        for client in self.data_router.clients:
            try:
                if client.is_remote:
                    client.prx.scanEnd(status)
                else:
                    client.callback.scan_end(status)
            except Ice.CloseConnectionException:
                self.data_router._connection_closed_callback(current.con)


class DataRouterI(DataRouter):
    def __init__(self):
        self.logger = mamba_server.logger
        self.clients = []
        self.local_clients = {}
        self.conn_to_client = {}
        self.subscription = {}
        self.data_process_chain = []
        self.keys = {}
        self.scan_id = 0
        self.recv_interface = None

    @client_verify
    def registerClient(self, client: DataClient, current=None):
        self.logger.info("Remote data client connected: "
                         + Ice.identityToString(client.ice_getIdentity()))
        client_prx = client.ice_fixed(current.con)
        client = Client(True, client_prx, None)
        self.clients.append(client)
        self.conn_to_client[current.con] = client
        self.subscription[client] = []
        set_connection_closed_callback(
            current.con,
            self._connection_closed_callback
        )

    def local_register_client(self, name, callback: DataClientCallback):
        self.logger.info(f"Local data client registered: {name}")
        client = Client(False, None, callback)
        self.clients.append(client)
        self.local_clients[name] = client
        self.subscription[client] = []

    def append_data_processor(self, data_processor: DataProcessor):
        self.data_process_chain.append(data_processor)

    def clear_data_processors(self):
        self.data_process_chain = []

    def remove_data_processor(self, data_processor: DataProcessor):
        self.data_process_chain.remove(data_processor)

    @client_verify
    def subscribe(self, items, current=None):
        client = self.conn_to_client[current.con]
        self.subscription[client] = items

    @client_verify
    def subscribeAll(self, current=None):
        client = self.conn_to_client[current.con]
        self.subscription[client] = ["*"]

    @client_verify
    def unsubscribe(self, items, current=None):
        client = self.conn_to_client[current.con]
        for item in items:
            try:
                self.subscription[client].remove(item)
            except ValueError:
                pass

    def local_subscribe(self, name, items):
        client = self.local_clients[name]
        self.subscription[client] = items

    def local_subscribe_all(self, name):
        client = self.local_clients[name]
        self.subscription[client] = ["*"]

    def get_recv_interface(self):
        if not self.recv_interface:
            self.recv_interface = DataRouterRecvI(self)

        return self.recv_interface

    def _connection_closed_callback(self, conn):
        client = self.conn_to_client[conn]
        self.clients.remove(client)
        del self.subscription[client]
        conn_to_delete = None
        for conn, _client in self.conn_to_client.items():
            if _client == client:
                conn_to_delete = conn
                break
        del self.conn_to_client[conn_to_delete]


def initialize(communicator, public_adapter, internal_adapter):
    mamba_server.data_router = DataRouterI()

    public_adapter.add(mamba_server.data_router,
                       communicator.stringToIdentity("DataRouter"))
    internal_adapter.add(mamba_server.data_router.get_recv_interface(),
                         communicator.stringToIdentity("DataRouterRecv"))

    mamba_server.logger.info("DataRouter initialized.")
