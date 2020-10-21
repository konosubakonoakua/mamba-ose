import os
import datetime
import argparse
import logging
import Ice

import mamba_server
import mamba_server.session_manager as session_manager
import mamba_server.terminal_host as terminal
import mamba_server.data_router as data_router
import mamba_server.device_manager as device_manager
import mamba_server.file_writer as file_writer
import mamba_server.scan_manager as scan_manager
from utils import general_utils


def main():
    parser = argparse.ArgumentParser(
        description="The host of Mamba application."
    )
    parser.add_argument("-c", "--config", dest="config", type=str,
                        default=None, help="the path to the config file")

    args = parser.parse_args()

    mamba_server.session_start_at = datetime.datetime.now().strftime("%Y%m%d_%H%M")

    # --- Ice properties setup ---

    ice_props = Ice.createProperties()

    # ACM setup for bidirectional connections.
    ice_props.setProperty("Ice.ACM.Close", "4")  # CloseOnIdleForceful
    ice_props.setProperty("Ice.ACM.Heartbeat", "0")  # HeartbeatOff
    ice_props.setProperty("Ice.ACM.Timeout", "30")

    # Increase the thread pool, to handle nested RPC calls
    # If the thread pool is exhausted, new RPC call will block the mamba_server.
    # When a deadlock happens, one can use
    #    ice_props.setProperty("Ice.Trace.ThreadPool", "1")
    # to see the what's going on in the thread pool.
    # See https://doc.zeroc.com/ice/3.6/client-server-features/the-ice-threading-model/nested-invocations
    # for more information.
    ice_props.setProperty("Ice.ThreadPool.Client.Size", "1")
    ice_props.setProperty("Ice.ThreadPool.Client.SizeMax", "10")
    ice_props.setProperty("Ice.ThreadPool.Server.Size", "1")
    ice_props.setProperty("Ice.ThreadPool.Server.SizeMax", "10")

    ice_init_data = Ice.InitializationData()
    ice_init_data.properties = ice_props

    with Ice.initialize(ice_init_data) as ic:
        mamba_server.communicator = ic
        mamba_server.logger = logger = logging.getLogger()

        if args.config:
            assert os.path.exists(args.config), "Invalid config path!"
            logger.info(f"Loading config file {args.config}")
            mamba_server.config_filename = args.config
        elif os.path.exists("server_config.yaml"):
            logger.info(f"Loading config file ./server_config.yaml")
            mamba_server.config_filename = "server_config.yaml"
        else:
            logger.warning("No config file discovered. Using the default one.")
            mamba_server.config_filename = general_utils.solve_filepath(
                "server_config.yaml", os.path.realpath(__file__))

        mamba_server.config = general_utils.load_config(
            mamba_server.config_filename)
        general_utils.setup_logger(logger)

        mamba_server.logger.info(f"Server started. Bind at {general_utils.get_bind_endpoint()}.")
        public_adapter = ic.createObjectAdapterWithEndpoints("MambaServer",
                                                      general_utils.get_bind_endpoint())
        mamba_server.public_adapter = public_adapter

        internal_adapter = ic.createObjectAdapterWithEndpoints("MambaServerInternal",
                                                               general_utils.get_internal_endpoint())
        mamba_server.internal_adapter = internal_adapter

        session_manager.initialize(ic, public_adapter)
        terminal.initialize(ic, public_adapter, internal_adapter)
        data_router.initialize(ic, public_adapter, internal_adapter)
        device_manager.initialize(ic, public_adapter, internal_adapter, mamba_server.terminal)
        file_writer.initialize(ic, public_adapter,
                               mamba_server.device_manager,
                               mamba_server.data_router)
        scan_manager.initialize(ic, public_adapter, mamba_server.terminal,
                                mamba_server.data_router)

        public_adapter.activate()
        internal_adapter.activate()

        try:
            ic.waitForShutdown()
        except KeyboardInterrupt:
            pass
