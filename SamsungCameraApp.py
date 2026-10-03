import sys
import os
import re
import html
import time
import socket
import shutil
import threading
import subprocess
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import http.server
import socketserver

from datetime import datetime
from PIL import Image

from PySide6.QtCore import (
    Qt,
    QObject,
    Signal,
    QSize,
)

from PySide6.QtGui import (
    QPixmap,
    QImage,
    QCursor,
)

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QCheckBox,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QScrollArea,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QFrame,
)


# =========================================================
# CAMERA SETTINGS
# =========================================================

CAMERA_IP = "192.168.101.1"

DEVICE_URL = f"http://{CAMERA_IP}:7676/smp_6_"
CONTROL_URL = f"http://{CAMERA_IP}:7676/smp_11_"
EVENT_URL = f"http://{CAMERA_IP}:7676/smp_12_"

SSDP_GROUP = "239.255.255.250"
SSDP_PORT = 1901

CALLBACK_PORT = 9999

stop_event = threading.Event()


# =========================================================
# MAC NETWORK INFO
# =========================================================

def get_mac_ip():

    try:
        return subprocess.check_output(
            ["ipconfig", "getifaddr", "en0"]
        ).decode().strip()

    except Exception:
        return None


def get_mac_address():

    try:

        output = subprocess.check_output(
            ["ifconfig", "en0"]
        ).decode()

        match = re.search(
            r"ether\s+([0-9a-fA-F:]{17})",
            output
        )

        if match:
            return match.group(1).lower()

    except Exception:
        pass

    return "UNKNOWN"


def get_samsung_user_agent():

    return "SEC_DSC_" + get_mac_address()


# =========================================================
# CAMERA DATE HELPERS
# =========================================================

def camera_date_timestamp(date_string):

    if not date_string:
        return 0

    try:

        clean = date_string.replace(
            "Z",
            "+00:00"
        )

        return datetime.fromisoformat(
            clean
        ).timestamp()

    except Exception:
        return 0


def format_camera_date(date_string):

    if not date_string:
        return "Date unavailable"

    try:

        clean = date_string.replace(
            "Z",
            "+00:00"
        )

        date = datetime.fromisoformat(
            clean
        )

        if "T" in date_string:

            return date.strftime(
                "%d %b %Y • %I:%M %p"
            )

        return date.strftime(
            "%d %b %Y"
        )

    except Exception:
        return date_string


# =========================================================
# SSDP LISTENER
# =========================================================

def ssdp_listener(mac_ip):

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
        socket.IPPROTO_UDP
    )

    sock.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    try:
        sock.bind(
            ("", SSDP_PORT)
        )

    except Exception as e:

        print(
            "SSDP bind error:",
            e
        )

        return

    membership = (
        socket.inet_aton(
            SSDP_GROUP
        )
        +
        socket.inet_aton(
            mac_ip
        )
    )

    try:

        sock.setsockopt(
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            membership
        )

    except Exception as e:

        print(
            "Multicast join warning:",
            e
        )

    sock.settimeout(
        1
    )

    while not stop_event.is_set():

        try:

            data, addr = sock.recvfrom(
                65535
            )

            text = data.decode(
                errors="ignore"
            )

            if addr[0] == CAMERA_IP:

                lower = text.lower()

                if "ssdp:alive" in lower:

                    print(
                        "Camera SSDP alive"
                    )

                elif "ssdp:byebye" in lower:

                    print(
                        "Camera SSDP byebye"
                    )

        except socket.timeout:
            pass

        except Exception as e:

            if not stop_event.is_set():

                print(
                    "SSDP listener error:",
                    e
                )

    try:
        sock.close()

    except Exception:
        pass


# =========================================================
# SAMSUNG SSDP DISCOVERY
# =========================================================

def samsung_msearch(mac_ip):

    user_agent = (
        get_samsung_user_agent()
    )

    print(
        "Mac IP:",
        mac_ip
    )

    print(
        "Samsung User-Agent:",
        user_agent
    )

    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_GROUP}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: ssdp:all\r\n"
        f"USER-AGENT: {user_agent}\r\n"
        "ACCESS-METHOD: manual\r\n"
        "\r\n"
    )

    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
        socket.IPPROTO_UDP
    )

    sock.setsockopt(
        socket.IPPROTO_IP,
        socket.IP_MULTICAST_IF,
        socket.inet_aton(
            mac_ip
        )
    )

    sock.setsockopt(
        socket.IPPROTO_IP,
        socket.IP_MULTICAST_TTL,
        2
    )

    sock.bind(
        (
            mac_ip,
            0
        )
    )

    sock.settimeout(
        1.5
    )

    camera_found = False

    for attempt in range(
        1,
        6
    ):

        if stop_event.is_set():
            break

        print(
            f"M-SEARCH attempt {attempt}/5"
        )

        try:

            sock.sendto(
                message.encode(),
                (
                    SSDP_GROUP,
                    SSDP_PORT
                )
            )

        except Exception as e:

            print(
                "M-SEARCH send error:",
                e
            )

            continue

        start = time.time()

        while (
            time.time() - start < 2
            and not stop_event.is_set()
        ):

            try:

                data, addr = sock.recvfrom(
                    65535
                )

                response = data.decode(
                    errors="ignore"
                )

                if addr[0] == CAMERA_IP:

                    camera_found = True

                    if (
                        "MediaServer"
                        in response
                        or "smp_6_"
                        in response
                        or "ContentDirectory"
                        in response
                    ):

                        print(
                            "WB250F discovered"
                        )

            except socket.timeout:
                break

            except Exception as e:

                print(
                    "M-SEARCH receive error:",
                    e
                )

                break

        if camera_found:
            break

        time.sleep(
            1
        )

    sock.close()

    return camera_found


# =========================================================
# CALLBACK SERVER
# =========================================================

class ReusableTCPServer(
    socketserver.TCPServer
):

    allow_reuse_address = True


class CallbackHandler(
    http.server.BaseHTTPRequestHandler
):

    def do_NOTIFY(self):

        length = int(
            self.headers.get(
                "Content-Length",
                0
            )
        )

        if length:

            body = self.rfile.read(
                length
            ).decode(
                errors="ignore"
            )

            print(
                "Camera GENA event:",
                body
            )

        self.send_response(
            200
        )

        self.end_headers()


    def log_message(
        self,
        format,
        *args
    ):

        return


def start_callback_server(mac_ip):

    server = ReusableTCPServer(
        (
            mac_ip,
            CALLBACK_PORT
        ),
        CallbackHandler
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True
    )

    thread.start()

    return server


# =========================================================
# DEVICE DESCRIPTION
# =========================================================

def download_device_description():

    req = urllib.request.Request(
        DEVICE_URL
    )

    req.add_header(
        "USER-AGENT",
        get_samsung_user_agent()
    )

    try:

        with urllib.request.urlopen(
            req,
            timeout=10
        ) as response:

            return response.read()

    except Exception as e:

        print(
            "Device description error:",
            e
        )

        return None


# =========================================================
# GENA
# =========================================================

def subscribe_to_camera(mac_ip):

    callback = (
        f"<http://{mac_ip}:"
        f"{CALLBACK_PORT}/event>"
    )

    request = urllib.request.Request(
        EVENT_URL,
        method="SUBSCRIBE"
    )

    request.add_header(
        "CALLBACK",
        callback
    )

    request.add_header(
        "NT",
        "upnp:event"
    )

    request.add_header(
        "TIMEOUT",
        "Second-1800"
    )

    request.add_header(
        "USER-AGENT",
        get_samsung_user_agent()
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            sid = response.headers.get(
                "SID"
            )

            print(
                "GENA SID:",
                sid
            )

            return sid

    except Exception as e:

        print(
            "SUBSCRIBE error:",
            e
        )

        return None


def renew_subscription(sid):

    if not sid:
        return False

    request = urllib.request.Request(
        EVENT_URL,
        method="SUBSCRIBE"
    )

    request.add_header(
        "SID",
        sid
    )

    request.add_header(
        "TIMEOUT",
        "Second-1800"
    )

    request.add_header(
        "USER-AGENT",
        get_samsung_user_agent()
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=10
        ):
            return True

    except Exception as e:

        print(
            "GENA renewal failed:",
            e
        )

        return False


def unsubscribe_from_camera(sid):

    if not sid:
        return

    request = urllib.request.Request(
        EVENT_URL,
        method="UNSUBSCRIBE"
    )

    request.add_header(
        "SID",
        sid
    )

    request.add_header(
        "USER-AGENT",
        get_samsung_user_agent()
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=2
        ) as response:

            print(
                "Camera subscription removed:",
                response.status
            )

    except Exception as e:

        # Camera may already have dropped
        # the connection. That's okay.
        print(
            "UNSUBSCRIBE:",
            e
        )


# =========================================================
# SOAP
# =========================================================

def soap_request(
    action,
    arguments
):

    service_type = (
        "urn:schemas-upnp-org:"
        "service:ContentDirectory:1"
    )

    args_xml = ""

    for key, value in arguments.items():

        args_xml += (
            f"<{key}>"
            f"{value}"
            f"</{key}>"
        )

    body = f"""<?xml version="1.0"?>
<s:Envelope
 xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"
 s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
<s:Body>
<u:{action}
 xmlns:u="{service_type}">
{args_xml}
</u:{action}>
</s:Body>
</s:Envelope>
"""

    request = urllib.request.Request(
        CONTROL_URL,
        data=body.encode(),
        method="POST"
    )

    request.add_header(
        "Content-Type",
        'text/xml; charset="utf-8"'
    )

    request.add_header(
        "SOAPACTION",
        f'"{service_type}#{action}"'
    )

    request.add_header(
        "USER-AGENT",
        get_samsung_user_agent()
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            return response.read()

    except urllib.error.HTTPError as e:

        print(
            "SOAP HTTP error:",
            e.code,
            e.reason
        )

        return None

    except Exception as e:

        if not stop_event.is_set():

            print(
                "SOAP error:",
                e
            )

        return None


# =========================================================
# PARSE CAMERA PHOTOS
# =========================================================

def parse_browse_response(
    response_data
):

    root = ET.fromstring(
        response_data
    )

    result = None

    for element in root.iter():

        if element.tag.endswith(
            "Result"
        ):

            result = element
            break

    if result is None:
        return []

    didl = html.unescape(
        result.text or ""
    )

    didl_root = ET.fromstring(
        didl
    )

    photos = []

    for item in didl_root:

        if not item.tag.endswith(
            "item"
        ):

            continue

        photo = {
            "title": "Unknown",
            "date": None,
            "original": None,
            "thumbnail": None,
            "preview": None,
        }

        for child in item:

            if child.tag.endswith(
                "title"
            ):

                photo["title"] = (
                    child.text
                    or "Unknown"
                )

            elif child.tag.endswith(
                "date"
            ):

                photo["date"] = (
                    child.text
                    or None
                )

            elif child.tag.endswith(
                "res"
            ):

                url = child.text

                protocol = child.attrib.get(
                    "protocolInfo",
                    ""
                )

                resolution = child.attrib.get(
                    "resolution",
                    ""
                )

                if "JPEG_LRG" in protocol:

                    photo["original"] = url

                elif "JPEG_TN" in protocol:

                    photo["thumbnail"] = url

                elif (
                    "JPEG_SM" in protocol
                    or resolution
                    not in (
                        "",
                        "160x120"
                    )
                ):

                    photo["preview"] = url

        if photo["original"]:

            photos.append(
                photo
            )

    # Newest first
    photos.sort(
        key=lambda photo:
            camera_date_timestamp(
                photo.get(
                    "date"
                )
            ),
        reverse=True
    )

    return photos


def browse_camera_photos():

    response = soap_request(
        "Browse",
        {
            "ObjectID":
                "1",

            "BrowseFlag":
                "BrowseDirectChildren",

            "Filter":
                "*",

            "StartingIndex":
                "0",

            "RequestedCount":
                "500",

            "SortCriteria":
                ""
        }
    )

    if not response:
        return []

    return parse_browse_response(
        response
    )


# =========================================================
# RESTORE ORIGINAL PHOTO DATE
# =========================================================

def restore_photo_dates(file_path):

    """
    The downloaded JPEG bytes are not modified.

    This reads the EXIF capture date and uses it
    for the Mac file's modified/access timestamps.

    If Apple's SetFile utility exists, it also
    restores the Finder creation date.
    """

    try:

        with Image.open(
            file_path
        ) as image:

            exif = image.getexif()

            # EXIF tags:
            #
            # 36867 = DateTimeOriginal
            # 36868 = DateTimeDigitized
            # 306   = DateTime

            date_string = (
                exif.get(36867)
                or exif.get(36868)
                or exif.get(306)
            )

        if not date_string:

            print(
                "No EXIF capture date:",
                file_path
            )

            return

        photo_date = datetime.strptime(
            str(date_string),
            "%Y:%m:%d %H:%M:%S"
        )

        timestamp = (
            photo_date.timestamp()
        )

        # Modified + accessed time
        os.utime(
            file_path,
            (
                timestamp,
                timestamp
            )
        )

        # macOS Finder creation date
        setfile = shutil.which(
            "SetFile"
        )

        if setfile:

            formatted = (
                photo_date.strftime(
                    "%m/%d/%Y %H:%M:%S"
                )
            )

            subprocess.run(
                [
                    setfile,
                    "-d",
                    formatted,
                    file_path
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )

        print(
            "Photo date restored:",
            date_string
        )

    except Exception as e:

        print(
            "Could not restore photo date:",
            e
        )


# =========================================================
# KEEPALIVE
# =========================================================

def camera_health_loop():

    count = 0

    while not stop_event.wait(
        20
    ):

        count += 1

        response = soap_request(
            "Browse",
            {
                "ObjectID":
                    "1",

                "BrowseFlag":
                    "BrowseDirectChildren",

                "Filter":
                    "*",

                "StartingIndex":
                    "0",

                "RequestedCount":
                    "1",

                "SortCriteria":
                    ""
            }
        )

        if response:

            print(
                f"[KEEPALIVE {count}] "
                "Browse successful"
            )

        else:

            print(
                f"[KEEPALIVE {count}] "
                "Browse failed"
            )


def gena_renew_loop(
    sid
):

    while not stop_event.wait(
        1200
    ):

        renew_subscription(
            sid
        )


# =========================================================
# SIGNALS
# =========================================================

class AppSignals(
    QObject
):

    status = Signal(
        str
    )

    connection_finished = Signal(
        object
    )

    connection_error = Signal(
        str
    )

    thumbnail_loaded = Signal(
        int,
        bytes
    )

    progress = Signal(
        int,
        str
    )

    download_finished = Signal(
        int,
        int,
        str
    )


# =========================================================
# PHOTO CARD
# =========================================================

def get_exif_datetime_from_bytes(image_data):

    try:
        from io import BytesIO

        with Image.open(BytesIO(image_data)) as image:

            exif = image.getexif()

            date_string = (
                exif.get(36867)
                or exif.get(36868)
                or exif.get(306)
            )

            if not date_string:
                return None

            return datetime.strptime(
                str(date_string),
                "%Y:%m:%d %H:%M:%S"
            )

    except Exception:
        return None
    
class PhotoCard(
    QFrame
):

    selection_changed = Signal()

    def __init__(
        self,
        index,
        photo
    ):

        super().__init__()

        self.index = index
        self.photo = photo

        self.setObjectName(
            "photoCard"
        )

        self.setFixedWidth(
            210
        )

        self.setCursor(
            QCursor(
                Qt.PointingHandCursor
            )
        )

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            9,
            9,
            9,
            9
        )

        layout.setSpacing(
            6
        )

        # Thumbnail

        self.image_label = QLabel(
            "Loading..."
        )

        self.image_label.setAlignment(
            Qt.AlignCenter
        )

        self.image_label.setFixedSize(
            190,
            145
        )

        self.image_label.setStyleSheet(
            """
            QLabel {
                background: #eeeeee;
                border-radius: 7px;
            }
            """
        )

        layout.addWidget(
            self.image_label
        )

        # Checkbox + filename

        self.checkbox = QCheckBox(
            photo["title"]
        )

        self.checkbox.setStyleSheet(
            """
            QCheckBox {
                font-size: 13px;
                font-weight: 500;
            }
            """
        )

        self.checkbox.stateChanged.connect(
            self.on_selection_changed
        )

        layout.addWidget(
            self.checkbox
        )

        # Date

        date_text = format_camera_date(
            photo.get(
                "date"
            )
        )

        self.date_label = QLabel(
            date_text
        )

        self.date_label.setStyleSheet(
            """
            QLabel {
                color: #777777;
                font-size: 11px;
            }
            """
        )

        layout.addWidget(
            self.date_label
        )

        self.update_selection_style()


    def is_selected(self):

        return (
            self.checkbox.isChecked()
        )


    def set_selected(
        self,
        selected
    ):

        self.checkbox.setChecked(
            selected
        )


    def toggle_selection(self):

        self.checkbox.setChecked(
            not self.checkbox.isChecked()
        )


    def on_selection_changed(self):

        self.update_selection_style()

        self.selection_changed.emit()


    def update_selection_style(self):

        if self.checkbox.isChecked():

            self.setStyleSheet(
                """
                QFrame#photoCard {
                    border: 2px solid #007AFF;
                    border-radius: 10px;
                    background: rgba(0, 122, 255, 0.08);
                }
                """
            )

        else:

            self.setStyleSheet(
                """
                QFrame#photoCard {
                    border: 1px solid #d8d8d8;
                    border-radius: 10px;
                    background: transparent;
                }
                """
            )


    def mousePressEvent(
        self,
        event
    ):

        # Let the normal checkbox handle its
        # own click so it doesn't toggle twice.

        child = self.childAt(
            event.position().toPoint()
        )

        if child is not self.checkbox:

            self.toggle_selection()

        super().mousePressEvent(
            event
        )


    def set_thumbnail(
        self,
        image_data
    ):

        image = QImage.fromData(
            image_data
        )

        if image.isNull():

            self.image_label.setText(
                "No Preview"
            )

            return

        pixmap = QPixmap.fromImage(
            image
        )

        pixmap = pixmap.scaled(
            QSize(
                190,
                145
            ),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        self.image_label.setPixmap(
            pixmap
        )


# =========================================================
# MAIN WINDOW
# =========================================================

class MainWindow(
    QMainWindow
):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "Samsung Camera Transfer"
        )

        self.resize(
            1080,
            760
        )

        self.setMinimumSize(
            760,
            540
        )

        self.photos = []
        self.cards = []

        self.callback_server = None
        self.sid = None

        self.connected = False
        self.closing = False
        self.downloading = False

        self.signals = (
            AppSignals()
        )

        self.signals.status.connect(
            self.set_status
        )

        self.signals.connection_finished.connect(
            self.on_connected
        )

        self.signals.connection_error.connect(
            self.on_connection_error
        )

        self.signals.thumbnail_loaded.connect(
            self.on_thumbnail_loaded
        )

        self.signals.progress.connect(
            self.on_progress
        )

        self.signals.download_finished.connect(
            self.on_download_finished
        )

        self.build_ui()


    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        central = QWidget()

        self.setCentralWidget(
            central
        )

        main_layout = QVBoxLayout(
            central
        )

        main_layout.setContentsMargins(
            18,
            18,
            18,
            18
        )

        main_layout.setSpacing(
            12
        )

        # Header

        header = QHBoxLayout()

        title = QLabel(
            "Samsung WB250F"
        )

        title.setStyleSheet(
            """
            QLabel {
                font-size: 26px;
                font-weight: 600;
            }
            """
        )

        header.addWidget(
            title
        )

        header.addStretch()

        self.connect_button = QPushButton(
            "Connect to Camera"
        )

        self.connect_button.clicked.connect(
            self.connect_camera
        )

        header.addWidget(
            self.connect_button
        )

        main_layout.addLayout(
            header
        )

        # Status

        self.status_label = QLabel(
            "Put the WB250F in MobileLink → "
            "Select Files from Smartphone, then "
            "connect this Mac to the camera Wi-Fi."
        )

        self.status_label.setWordWrap(
            True
        )

        main_layout.addWidget(
            self.status_label
        )

        # Controls

        controls = QHBoxLayout()

        self.select_all_button = QPushButton(
            "Select All"
        )

        self.select_all_button.clicked.connect(
            self.select_all
        )

        self.select_all_button.setEnabled(
            False
        )

        controls.addWidget(
            self.select_all_button
        )

        self.clear_button = QPushButton(
            "Clear Selection"
        )

        self.clear_button.clicked.connect(
            self.clear_selection
        )

        self.clear_button.setEnabled(
            False
        )

        controls.addWidget(
            self.clear_button
        )

        self.selection_label = QLabel(
            "0 Selected"
        )

        self.selection_label.setStyleSheet(
            """
            QLabel {
                color: #666666;
                padding-left: 8px;
            }
            """
        )

        controls.addWidget(
            self.selection_label
        )

        controls.addStretch()

        self.download_button = QPushButton(
            "Download Selected"
        )

        self.download_button.clicked.connect(
            self.download_selected
        )

        self.download_button.setEnabled(
            False
        )

        controls.addWidget(
            self.download_button
        )

        main_layout.addLayout(
            controls
        )

        # Progress

        self.progress_bar = QProgressBar()

        self.progress_bar.setRange(
            0,
            100
        )

        self.progress_bar.setValue(
            0
        )

        self.progress_bar.setTextVisible(
            False
        )

        main_layout.addWidget(
            self.progress_bar
        )

        # Gallery

        self.scroll_area = QScrollArea()

        self.scroll_area.setWidgetResizable(
            True
        )

        self.scroll_area.setFrameShape(
            QFrame.NoFrame
        )

        self.gallery_widget = QWidget()

        self.gallery_layout = QGridLayout(
            self.gallery_widget
        )

        self.gallery_layout.setAlignment(
            Qt.AlignTop
            |
            Qt.AlignLeft
        )

        self.gallery_layout.setHorizontalSpacing(
            12
        )

        self.gallery_layout.setVerticalSpacing(
            12
        )

        self.scroll_area.setWidget(
            self.gallery_widget
        )

        main_layout.addWidget(
            self.scroll_area
        )


    # =====================================================
    # CONNECTION
    # =====================================================

    def connect_camera(self):

        if self.connected:
            return

        stop_event.clear()

        self.connect_button.setEnabled(
            False
        )

        self.set_status(
            "Connecting to WB250F..."
        )

        thread = threading.Thread(
            target=self.connection_worker,
            daemon=True
        )

        thread.start()


    def connection_worker(self):

        mac_ip = get_mac_ip()

        if not mac_ip:

            self.signals.connection_error.emit(
                "Could not find the Mac Wi-Fi IP.\n\n"
                "Make sure this Mac is connected to "
                "the WB250F Wi-Fi network."
            )

            return

        self.signals.status.emit(
            f"Starting Samsung MobileLink discovery..."
        )

        try:

            listener_thread = threading.Thread(
                target=ssdp_listener,
                args=(
                    mac_ip,
                ),
                daemon=True
            )

            listener_thread.start()

            time.sleep(
                1
            )

            self.callback_server = (
                start_callback_server(
                    mac_ip
                )
            )

        except Exception as e:

            self.signals.connection_error.emit(
                "Could not start the camera session.\n\n"
                f"{e}"
            )

            return

        self.signals.status.emit(
            "Searching for Samsung WB250F..."
        )

        camera_found = (
            samsung_msearch(
                mac_ip
            )
        )

        if stop_event.is_set():
            return

        if camera_found:

            self.signals.status.emit(
                "WB250F found — establishing session..."
            )

        else:

            self.signals.status.emit(
                "Trying direct camera connection..."
            )

        description = (
            download_device_description()
        )

        if stop_event.is_set():
            return

        if not description:

            self.signals.connection_error.emit(
                "The WB250F could not be reached.\n\n"
                "Check that:\n"
                "• Camera is in MobileLink\n"
                "• Select Files from Smartphone is selected\n"
                "• Mac is connected to AP_SSC_WB250..."
            )

            return

        self.sid = (
            subscribe_to_camera(
                mac_ip
            )
        )

        if stop_event.is_set():
            return

        self.signals.status.emit(
            "Reading photos from camera..."
        )

        photos = (
            browse_camera_photos()
        )

        if stop_event.is_set():
            return

        if not photos:

            self.signals.connection_error.emit(
                "The camera connected, but no photos were found."
            )

            return

        # Keep session alive

        health_thread = threading.Thread(
            target=camera_health_loop,
            daemon=True
        )

        health_thread.start()

        if self.sid:

            renewal_thread = threading.Thread(
                target=gena_renew_loop,
                args=(
                    self.sid,
                ),
                daemon=True
            )

            renewal_thread.start()

        self.signals.connection_finished.emit(
            photos
        )


    def on_connected(
        self,
        photos
    ):

        self.connected = True
        self.photos = photos

        self.connect_button.setText(
            "Connected"
        )

        self.connect_button.setEnabled(
            False
        )

        self.select_all_button.setEnabled(
            True
        )

        self.clear_button.setEnabled(
            True
        )

        self.set_status(
            f"Connected — {len(photos)} photos found."
        )

        self.show_photo_cards()


    def on_connection_error(
        self,
        message
    ):

        if self.closing:
            return

        self.connect_button.setEnabled(
            True
        )

        self.connect_button.setText(
            "Connect to Camera"
        )

        self.set_status(
            "Connection failed."
        )

        QMessageBox.critical(
            self,
            "Samsung Camera Transfer",
            message
        )


    # =====================================================
    # GALLERY
    # =====================================================

    def show_photo_cards(self):

        self.cards = []

        while self.gallery_layout.count():

            item = (
                self.gallery_layout.takeAt(
                    0
                )
            )

            widget = item.widget()

            if widget:
                widget.deleteLater()

        for index, photo in enumerate(
            self.photos
        ):

            card = PhotoCard(
                index,
                photo
            )

            card.selection_changed.connect(
                self.update_selection_count
            )

            self.cards.append(
                card
            )

            # 4 columns
            row = index // 4
            column = index % 4

            self.gallery_layout.addWidget(
                card,
                row,
                column
            )

        thread = threading.Thread(
            target=self.thumbnail_worker,
            daemon=True
        )

        thread.start()


    def thumbnail_worker(self):

        total = len(
            self.photos
        )

        for index, photo in enumerate(
            self.photos
        ):

            if stop_event.is_set():
                break

            url = (
                photo["thumbnail"]
                or photo["preview"]
            )

            if url:

                try:

                    request = urllib.request.Request(
                        url
                    )

                    request.add_header(
                        "USER-AGENT",
                        get_samsung_user_agent()
                    )

                    with urllib.request.urlopen(
                        request,
                        timeout=15
                    ) as response:

                        data = response.read()

                    exif_date = get_exif_datetime_from_bytes(
                        data
                    )

                    if exif_date:

                        self.photos[index]["display_date"] = (
                            exif_date.strftime(
                                "%d %b %Y • %I:%M %p"
                            )
                        )

                    self.signals.thumbnail_loaded.emit(
                        index,
                        data
                    )

                except Exception as e:

                    if not stop_event.is_set():

                        print(
                            "Thumbnail error:",
                            photo["title"],
                            e
                        )

            percent = int(
                (
                    (index + 1)
                    / total
                )
                * 100
            )

            self.signals.progress.emit(
                percent,
                f"Loading photos {index + 1}/{total}..."
            )

        if not stop_event.is_set():

            self.signals.progress.emit(
                0,
                f"Connected — {len(self.photos)} photos found."
            )


    def on_thumbnail_loaded(
        self,
        index,
        data
    ):

        if index < len(
            self.cards
        ):

            card = self.cards[index]

            card.set_thumbnail(
                data
            )

            display_date = (
                self.photos[index].get(
                    "display_date"
                )
            )

            if display_date:

                card.date_label.setText(
                    display_date
                )


    # =====================================================
    # SELECTION
    # =====================================================

    def selected_cards(self):

        return [
            card
            for card in self.cards
            if card.is_selected()
        ]


    def update_selection_count(self):

        count = len(
            self.selected_cards()
        )

        self.selection_label.setText(
            f"{count} Selected"
        )

        if count == 0:

            self.download_button.setText(
                "Download Selected"
            )

            self.download_button.setEnabled(
                False
            )

        elif count == 1:

            self.download_button.setText(
                "Download 1 Photo"
            )

            self.download_button.setEnabled(
                not self.downloading
            )

        else:

            self.download_button.setText(
                f"Download {count} Photos"
            )

            self.download_button.setEnabled(
                not self.downloading
            )


    def select_all(self):

        for card in self.cards:

            card.set_selected(
                True
            )

        self.update_selection_count()


    def clear_selection(self):

        for card in self.cards:

            card.set_selected(
                False
            )

        self.update_selection_count()


    # =====================================================
    # DOWNLOAD
    # =====================================================

    def download_selected(self):

        selected_cards = (
            self.selected_cards()
        )

        if not selected_cards:

            return

        selected = [
            card.photo
            for card in selected_cards
        ]

        folder = (
            QFileDialog.getExistingDirectory(
                self,
                "Choose Download Folder"
            )
        )

        if not folder:
            return

        self.downloading = True

        self.download_button.setEnabled(
            False
        )

        self.select_all_button.setEnabled(
            False
        )

        self.clear_button.setEnabled(
            False
        )

        thread = threading.Thread(
            target=self.download_worker,
            args=(
                selected,
                folder
            ),
            daemon=True
        )

        thread.start()


    def download_worker(
        self,
        selected,
        folder
    ):

        success = 0
        failed = 0

        total = len(
            selected
        )

        for index, photo in enumerate(
            selected,
            start=1
        ):

            if stop_event.is_set():
                break

            title = (
                photo["title"]
                or f"photo_{index}"
            )

            safe_title = re.sub(
                r'[\\/:*?"<>|]',
                "_",
                title
            )

            if not safe_title.lower().endswith(
                (
                    ".jpg",
                    ".jpeg"
                )
            ):

                safe_title += ".jpg"

            destination = os.path.join(
                folder,
                safe_title
            )

            # Don't overwrite an existing photo

            base, extension = (
                os.path.splitext(
                    destination
                )
            )

            duplicate_number = 1

            while os.path.exists(
                destination
            ):

                destination = (
                    f"{base}_{duplicate_number}"
                    f"{extension}"
                )

                duplicate_number += 1

            try:

                self.signals.progress.emit(
                    int(
                        (
                            (index - 1)
                            / total
                        )
                        * 100
                    ),
                    f"Downloading {index}/{total}: "
                    f"{photo['title']}"
                )

                request = urllib.request.Request(
                    photo["original"]
                )

                request.add_header(
                    "USER-AGENT",
                    get_samsung_user_agent()
                )

                with urllib.request.urlopen(
                    request,
                    timeout=120
                ) as response:

                    with open(
                        destination,
                        "wb"
                    ) as file:

                        while True:

                            if stop_event.is_set():
                                break

                            chunk = response.read(
                                256 * 1024
                            )

                            if not chunk:
                                break

                            file.write(
                                chunk
                            )

                if stop_event.is_set():

                    # Remove partial file
                    try:
                        os.remove(
                            destination
                        )
                    except Exception:
                        pass

                    break

                # Restore filesystem timestamps
                # from the JPEG's own EXIF date.
                restore_photo_dates(
                    destination
                )

                success += 1

            except Exception as e:

                failed += 1

                print(
                    "Download failed:",
                    photo["title"],
                    e
                )

            percent = int(
                (
                    index
                    / total
                )
                * 100
            )

            self.signals.progress.emit(
                percent,
                f"Downloading {index}/{total}: "
                f"{photo['title']}"
            )

        if not stop_event.is_set():

            self.signals.download_finished.emit(
                success,
                failed,
                folder
            )


    def on_progress(
        self,
        percent,
        text
    ):

        self.progress_bar.setValue(
            percent
        )

        self.set_status(
            text
        )


    def on_download_finished(
        self,
        success,
        failed,
        folder
    ):

        self.downloading = False

        self.progress_bar.setValue(
            0
        )

        self.select_all_button.setEnabled(
            True
        )

        self.clear_button.setEnabled(
            True
        )

        self.update_selection_count()

        if failed:

            message = (
                f"{success} photos downloaded.\n"
                f"{failed} failed."
            )

        else:

            message = (
                f"{success} photos downloaded successfully."
            )

        self.set_status(
            message
        )

        reply = QMessageBox.question(
            self,
            "Download Complete",
            message
            +
            "\n\nOpen the folder?"
        )

        if reply == QMessageBox.Yes:

            subprocess.Popen(
                [
                    "open",
                    folder
                ]
            )


    # =====================================================
    # STATUS
    # =====================================================

    def set_status(
        self,
        text
    ):

        self.status_label.setText(
            text
        )


    # =====================================================
    # DISCONNECT
    # =====================================================

    def disconnect_camera(self):

        if self.closing:
            print(
                "Disconnecting camera..."
            )

        # Immediately tell worker loops to end.
        stop_event.set()

        # End UPnP event subscription.
        if self.sid:

            unsubscribe_from_camera(
                self.sid
            )

            self.sid = None

        # Stop HTTP event callback server.
        if self.callback_server:

            try:

                self.callback_server.shutdown()

                self.callback_server.server_close()

            except Exception as e:

                print(
                    "Callback server shutdown:",
                    e
                )

            self.callback_server = None

        self.connected = False

        print(
            "Camera client session closed."
        )


    # =====================================================
    # CLOSE WINDOW
    # =====================================================

    def closeEvent(
        self,
        event
    ):

        if self.closing:

            event.accept()
            return

        self.closing = True

        print(
            "Closing Samsung Camera Transfer..."
        )

        self.disconnect_camera()

        event.accept()


# =========================================================
# START APP
# =========================================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        "Samsung Camera Transfer"
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )