import enum
import logging
import llp
import queue
import struct
import threading
from threading import Timer 

class SWPType(enum.IntEnum):
    DATA = ord('D')
    ACK = ord('A')

class SWPPacket:
    _PACK_FORMAT = '!BI'
    _HEADER_SIZE = struct.calcsize(_PACK_FORMAT)
    MAX_DATA_SIZE = 1400 # Leaves plenty of space for IP + UDP + SWP header 

    def __init__(self, type, seq_num, data=b''):
        self._type = type
        self._seq_num = seq_num
        self._data = data

    @property
    def type(self):
        return self._type

    @property
    def seq_num(self):
        return self._seq_num
    
    @property
    def data(self):
        return self._data

    def to_bytes(self):
        header = struct.pack(SWPPacket._PACK_FORMAT, self._type.value, 
                self._seq_num)
        return header + self._data
       
    @classmethod
    def from_bytes(cls, raw):
        header = struct.unpack(SWPPacket._PACK_FORMAT,
                raw[:SWPPacket._HEADER_SIZE])
        type = SWPType(header[0])
        seq_num = header[1]
        data = raw[SWPPacket._HEADER_SIZE:]
        return SWPPacket(type, seq_num, data)

    def __str__(self):
        return "%s %d %s" % (self._type.name, self._seq_num, repr(self._data))

class SWPSender:
    _SEND_WINDOW_SIZE = 5
    _TIMEOUT = 1

    def __init__(self, remote_address, loss_probability=0):
        self._llp_endpoint = llp.LLPEndpoint(remote_address=remote_address,
                loss_probability=loss_probability)

        # Start receive thread
        self._recv_thread = threading.Thread(target=self._recv)
        self._recv_thread.start()

        self._next_seq_num = 0
        self._send_buffer = {}
        self._timers = {}


    def send(self, data):
        for i in range(0, len(data), SWPPacket.MAX_DATA_SIZE):
            self._send(data[i:i+SWPPacket.MAX_DATA_SIZE])

    def _send(self, data):
        # Check if the send window is full
        if len(self._send_buffer) >= SWPSender._SEND_WINDOW_SIZE:
            return

        # Assign a sequence number to the data segment
        seq_num = self._next_seq_num
        self._next_seq_num += 1

        # Create an SWP packet
        packet = SWPPacket(SWPType.DATA, seq_num, data)

        # Add the packet to the dictionary send buffer
        self._send_buffer[seq_num] = packet

        # Send the packet
        self._llp_endpoint.send(packet.to_bytes())

        # Start a retransmission timer
        timer = Timer(SWPSender._TIMEOUT, self._retransmit, [seq_num])
        timer.start()
        self._timers[seq_num] = timer
        return
        
    def _retransmit(self, seq_num):
         # Check if the packet with the given sequence number is still in the buffer
        if seq_num in self._send_buffer:
            packet = self._send_buffer[seq_num]

            # Resend the packet
            logging.debug(f"Retransmitting packet with seq_num: {seq_num}")
            self._llp_endpoint.send(packet.to_bytes())

            # Restart the timer
            self._timers[seq_num].cancel()
            new_timer = Timer(SWPSender._TIMEOUT, self._retransmit, [seq_num])
            new_timer.start()
            self._timers[seq_num] = new_timer

        return 

    def _recv(self):
        while True:
            # Receive SWP packet
            raw = self._llp_endpoint.recv()
            if raw is None:
                continue
            packet = SWPPacket.from_bytes(raw)
            logging.debug("Received: %s" % packet)

            # TODO
            packet = SWPPacket.from_bytes(raw)
            logging.debug("Received: %s" % packet)

            # Process only ACK packets
            if packet.type == SWPType.ACK:
                ack_seq_num = packet.seq_num

                # Cancel the timer and remove acknowledged packets from the buffer
                for seq_num in list(self._send_buffer.keys()):
                    if seq_num <= ack_seq_num:
                        self._timers[seq_num].cancel()
                        del self._timers[seq_num]
                        del self._send_buffer[seq_num]
             
        return

class SWPReceiver:
    _RECV_WINDOW_SIZE = 5

    def __init__(self, local_address, loss_probability=0):
        self._llp_endpoint = llp.LLPEndpoint(local_address=local_address, 
                loss_probability=loss_probability)

        # Received data waiting for application to consume
        self._ready_data = queue.Queue()

        # Start receive thread
        self._recv_thread = threading.Thread(target=self._recv)
        self._recv_thread.start()
        
        # TODO: Add additional state variables
        self._expected_seq_num = 0
        self._buffer = {}

    def recv(self):
        return self._ready_data.get()

    def _recv(self):
        while True:
            # Receive data packet
            raw = self._llp_endpoint.recv()
            packet = SWPPacket.from_bytes(raw)
            logging.debug("Received: %s" % packet)
            
            # TODO
            if packet.type == SWPType.DATA:
                seq_num = packet.seq_num
                # Check if the packet is within the receive window
                if seq_num >= self._expected_seq_num and seq_num < self._expected_seq_num + SWPReceiver._RECV_WINDOW_SIZE:
                    self._buffer[seq_num] = packet.data
                    self._send_ack(seq_num)
                    self._process_buffer()
        return
    
    def _send_ack(self, seq_num):
        ack_packet = SWPPacket(SWPType.ACK, seq_num)
        self._llp_endpoint.send(ack_packet.to_bytes())
        logging.debug("Sent ACK: %s" % ack_packet)

    def _process_buffer(self):
        while self._expected_seq_num in self._buffer:
            data = self._buffer.pop(self._expected_seq_num)
            self._ready_data.put(data)
            self._expected_seq_num += 1

    
