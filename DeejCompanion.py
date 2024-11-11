import time
import queue
import rtmidi
import serial
import serial.tools.list_ports
import threading
import logging
import sys
import PySimpleGUI as sg
from PIL import Image, ImageDraw
import pystray

# Global variables
bridgeActive = False
logging.basicConfig(level=logging.DEBUG)
myfont = 'Any 12'
midi_ready = False
midiin_message_queue = queue.Queue()
midiout_message_queue = queue.Queue()
serialPort = ''
midiin = rtmidi.MidiIn()
midiout = rtmidi.MidiOut()
midiinPort = ''
midioutPort = ''

def popupError(s):
    sg.popup_error(s, font=myfont)

def get_midi_length(message):
    if len(message) == 0:
        return 100
    opcode = message[0]
    if opcode >= 0xf4:
        return 1
    if opcode in [0xf1, 0xf3]:
        return 2
    if opcode == 0xf2:
        return 3
    if opcode == 0xf0:
        if message[-1] == 0xf7:
            return len(message)
    opcode = opcode & 0xf0
    if opcode in [0x80, 0x90, 0xa0, 0xb0, 0xe0]:
        return 3
    if opcode in [0xc0, 0xd0]:
        return 2
    return 100

def serial_writer():
    global midi_ready, bridgeActive
    while not midi_ready:
        time.sleep(0.1)
    while bridgeActive:
        try:
            message = midiin_message_queue.get(timeout=0.4)
        except queue.Empty:
            continue
        logging.debug(message)
        value = bytearray(message)
        serialPort.write(value)

def serial_watcher():
    global midi_ready, bridgeActive
    receiving_message = []
    running_status = 0

    while not midi_ready:
        time.sleep(0.1)

    while bridgeActive:
        data = serialPort.read()
        if data:
            for elem in data:
                receiving_message.append(elem)
            if len(receiving_message) == 1:
                if (receiving_message[0] & 0xf0) != 0:
                    running_status = receiving_message[0]
                else:
                    receiving_message = [running_status, receiving_message[0]]
            message_length = get_midi_length(receiving_message)
            if message_length <= len(receiving_message):
                logging.debug(receiving_message)
                midiout_message_queue.put(receiving_message)
                receiving_message = []

class midi_input_handler(object):
    def __init__(self, port):
        self.port = port
        self._wallclock = time.time()

    def __call__(self, event, data=None):
        message, deltatime = event
        self._wallclock += deltatime
        midiin_message_queue.put(message)

def midi_watcher():
    global bridgeActive
    while bridgeActive:
        try:
            message = midiout_message_queue.get(timeout=0.4)
        except queue.Empty:
            continue
        midiout.send_message(message)

def startSerialMidiServer(serial_port_name, serial_baud, portIn, portOut):
    global serialPort, midiinPort, midioutPort, midi_ready, bridgeActive
    ok = True
    bridgeActive = True
    try:
        serialPort = serial.Serial(serial_port_name, serial_baud)
        midiinPort = midiin.open_port(portIn)
        midioutPort = midiout.open_port(portOut)
        midi_ready = True
        midiin.ignore_types(sysex=False, timing=False, active_sense=False)
        midiin.set_callback(midi_input_handler(midiinPort))
    except serial.serialutil.SerialException:
        popupError("Serial port opening error.")
        ok = False

    if ok:
        serialPort.timeout = 0.4
        s_watcher = threading.Thread(target=serial_watcher)
        s_writer = threading.Thread(target=serial_writer)
        m_watcher = threading.Thread(target=midi_watcher)
        s_watcher.start()
        s_writer.start()
        m_watcher.start()
    return ok

def stopSerialMidiServer():
    global serialPort, midiinPort, midioutPort, midi_ready, bridgeActive
    bridgeActive = False
    midi_ready = False
    del serialPort
    midiinPort.close_port()
    midioutPort.close_port()

spStrings = []
spPortnames = []

def setSerialPortnames():
    global spStrings, spPortnames
    spStrings = []
    spPortnames = []
    for n, (portname, desc, hwid) in enumerate(sorted(serial.tools.list_ports.comports())):
        spStrings.append(f'{portname} - {desc}')
        spPortnames.append(portname)

bdValues = []
def setBaudrates():
    global bdValues
    bdValues = serial.Serial.BAUDRATES

midiinPorts = []
midioutPorts = []
def getMidiPorts():
    global midiinPorts, midioutPorts
    midiinPorts = midiin.get_ports()
    midioutPorts = midiout.get_ports()

setSerialPortnames()
setBaudrates()
getMidiPorts()

wc = len(max(spStrings + midiinPorts + midioutPorts, key=len))
scbString = 'ScanPorts'
stbString = 'Start'
exbString = 'Exit'
wb = len(max([scbString, stbString, exbString], key=len))
spText = 'Serial port'
bdText = 'Baudrate'
s2mText = 'MIDI In'
m2sText = 'MIDI Out'
lb = len(max([spText, bdText, s2mText, m2sText], key=len))
csize = (wc, 1)
bsize = (wb, 1)
tsize = (lb, 1)
spSettings = 'SerialPortName'
bdSettings = 'Baudrate'
s2mSettings = 'Serial2MidiName'
m2sSettings = 'Midi2SerialName'
spCombo = sg.Combo(spStrings, size=csize, default_value=sg.UserSettings().get(spSettings, ''))
bdCombo = sg.Combo(bdValues, size=csize, default_value=sg.UserSettings().get(bdSettings, '115200'))
s2mCombo = sg.Combo(midiinPorts, size=csize, default_value=sg.UserSettings().get(s2mSettings, ''))
m2sCombo = sg.Combo(midioutPorts, size=csize, default_value=sg.UserSettings().get(m2sSettings, ''))
scKey = '-SCAN-'
stKey = '-START-'
exKey = '-EXIT-'
scButton = sg.Button(scbString, size=bsize, key=scKey, tooltip='Scan for Serial and MIDI ports')
stButton = sg.Button(stbString, size=bsize, key=stKey, tooltip='Start/stop the Serial-MIDI bridging')
exButton = sg.Button(exbString, size=bsize, key=exKey)

# Add system tray
tray = sg.SystemTray(menu=['', ['Show Window', 'Exit']], tooltip='Deej Companion App') 

layout = [
    [sg.Text(spText, size=tsize), sg.Text(':'), spCombo],
    [sg.Text(bdText, size=tsize), sg.Text(':'), bdCombo],
    [sg.Text(s2mText, size=tsize), sg.Text(':'), s2mCombo],
    [sg.Text(m2sText, size=tsize), sg.Text(':'), m2sCombo],
    [scButton, stButton, exButton]
]
enabled = False
window = sg.Window('Deej Companion App', layout, font=myfont)


# Load your custom icon
def create_icon():
    icon_path = 'icon.ico'  # Replace with your icon file path
    image = Image.open(icon_path)
    return image

def on_exit(icon, item):
    global bridgeActive
    bridgeActive = False
    icon.stop()
    window.close()

def on_show_window(icon, item):
    window.un_hide()
    window.bring_to_front()

# Function to handle tray icon logic
def tray_icon():
    # Create tray icon
    icon = pystray.Icon('Serial-MIDI bridge', create_icon())
    icon.menu = pystray.Menu(
        pystray.MenuItem('Show Window', on_show_window),
        pystray.MenuItem('Exit', on_exit)
    )
    icon.run()

# Start the tray icon in a separate thread
tray_thread = threading.Thread(target=tray_icon, daemon=True)
tray_thread.start()

def scanports():
    setSerialPortnames()
    getMidiPorts()
    # set new values and make sure the Combos have equal widths
    wc = len(max(spStrings+midiinPorts+midioutPorts,key=len)) # length of longest combo box string.
    wcsize = (wc, None)
    sel = spCombo.get()
    spCombo.Update(values=spStrings, value=sel, size=wcsize)
    bdCombo.Update(size=(wc, None))
    sel = s2mCombo.get()
    s2mCombo.Update(values=midiinPorts, value=sel, size=wcsize)
    sel = m2sCombo.get()
    m2sCombo.Update(values=midioutPorts, value=sel, size=wcsize)


# Main event loop for the window
while True:
    event, values = window.read(timeout=100)
    tray_event = tray.read(timeout=100)  # Read tray events separately

    # Handle window and system tray events
    if event == sg.WIN_CLOSED or event == exKey or tray_event == 'Exit':
        bridgeActive = False
        break
    elif event == scKey:
        scanports()
    elif event == stKey:
        if enabled:
            stButton.update(text='Start')
            enabled = False
            scButton.update(disabled=False)
            spCombo.update(disabled=False)
            bdCombo.update(disabled=False)
            s2mCombo.update(disabled=False)
            m2sCombo.update(disabled=False)
            stopSerialMidiServer()
        else:
            try:
                spi = spStrings.index(spCombo.get())
                bdi = bdValues.index(bdCombo.get())
                s2mi = midiinPorts.index(s2mCombo.get())
                m2si = midioutPorts.index(m2sCombo.get())
                ok = startSerialMidiServer(spPortnames[spi], bdValues[bdi], s2mi, m2si)
                if ok:
                    stButton.update(text='Stop')
                    enabled = True
                    scButton.update(disabled=True)
                    spCombo.update(disabled=True)
                    bdCombo.update(disabled=True)
                    s2mCombo.update(disabled=True)
                    m2sCombo.update(disabled=True)
            except Exception as e:
                popupError('Select all values\n' + str(e))
    elif event == '__TIMEOUT__':
        # Check if the window is minimized, if so, hide it
        if window.TKroot.state() == 'iconic':
            window.hide()
        continue

# Save settings on exit
sg.user_settings_set_entry(spSettings, spCombo.get())
sg.user_settings_set_entry(bdSettings, bdCombo.get())
sg.user_settings_set_entry(s2mSettings, s2mCombo.get())
sg.user_settings_set_entry(m2sSettings, m2sCombo.get())
window.close()