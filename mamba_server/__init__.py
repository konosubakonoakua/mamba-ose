import logging

from .session_manager import verify

try:
    logger
except NameError:
    logger = logging.getLogger()

session_start_at = ""

logger = None
config = None
communicator = None
session = None

public_adapter = None
internal_adapter = None

terminal = None
data_router = None
device_manager = None
file_writer_host = None
scan_manager = None
