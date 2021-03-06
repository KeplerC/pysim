#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" pySim: SIM Card commands according to ISO 7816-4 and TS 11.11
"""

#
# Copyright (C) 2009-2010  Sylvain Munaut <tnt@246tNt.com>
# Copyright (C) 2010       Harald Welte <laforge@gnumonks.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from pySim.utils import rpad, b2h

class SimCardCommands(object):
	def __init__(self, transport):
		self._tp = transport;
		self._cla_byte = "00"
		self.sel_ctrl = "0000"

	# Extract a single FCP item from TLV
	def __parse_fcp(self, fcp):
		# see also: ETSI TS 102 221, chapter 11.1.1.3.1 Response for MF,
		# DF or ADF
		from pytlv.TLV import TLV
		tlvparser = TLV(['82', '83', '84', 'a5', '8a', '8b', '8c', '80', 'ab', 'c6', '81', '88'])

		# pytlv is case sensitive!
		fcp = fcp.lower()

		if fcp[0:2] != '62':
			return None
			#raise ValueError('Tag of the FCP template does not match, expected 62 but got %s'%fcp[0:2])

		# Unfortunately the spec is not very clear if the FCP length is
		# coded as one or two byte vale, so we have to try it out by
		# checking if the length of the remaining TLV string matches
		# what we get in the length field.
		# See also ETSI TS 102 221, chapter 11.1.1.3.0 Base coding.
		exp_tlv_len = int(fcp[2:4], 16)
		if len(fcp[4:])/2 == exp_tlv_len:
			skip = 4
		else:
			exp_tlv_len = int(fcp[2:6], 16)
			if len(fcp[4:])/2 == exp_tlv_len:
				skip = 6

		# Skip FCP tag and length
		tlv = fcp[skip:]
                
		parsed_result = tlvparser.parse(tlv)
                print(parsed_result)
                return parsed_result

	# Tell the length of a record by the card response
	# USIMs respond with an FCP template, which is different
	# from what SIMs responds. See also:
	# USIM: ETSI TS 102 221, chapter 11.1.1.3 Response Data
	# SIM: GSM 11.11, chapter 9.2.1 SELECT
	def __record_len(self, r):
		if self.sel_ctrl == "0004":
			tlv_parsed = self.__parse_fcp(r[-1])
			file_descriptor = tlv_parsed['82']
			# See also ETSI TS 102 221, chapter 11.1.1.4.3 File Descriptor
			return int(file_descriptor[4:8], 16)
		else:
			return int(r[-1][28:30], 16)

	# Tell the length of a binary file. See also comment
	# above.
	def __len(self, r):
		if self.sel_ctrl == "0004":
			tlv_parsed = self.__parse_fcp(r[-1])
			return int(tlv_parsed['80'], 16)
		else:
			return int(r[-1][4:8], 16)

	def get_atr(self):
		return self._tp.get_atr()

	@property
	def cla_byte(self):
		return self._cla_byte
	@cla_byte.setter
	def cla_byte(self, value):
		self._cla_byte = value

	@property
	def sel_ctrl(self):
		return self._sel_ctrl
	@sel_ctrl.setter
	def sel_ctrl(self, value):
		self._sel_ctrl = value

	def select_file(self, dir_list):
		rv = []
                print("Current directory list: " + str(dir_list))
		for i in dir_list:
			data, sw = self._tp.send_apdu_checksw(self.cla_byte + "a4" + self.sel_ctrl + "02" + i)
			rv.append(data)
		return rv

	def select_adf(self, aid):
		aidlen = ("0" + format(len(aid)/2, 'x'))[-2:]
		return self._tp.send_apdu_checksw(self.cla_byte + "a4" + "0404" + aidlen + aid)

	def read_binary(self, ef, length=None, offset=0):
		if not hasattr(type(ef), '__iter__'):
			ef = [ef]
		r = self.select_file(ef)
		if len(r[-1]) == 0:
			return (None, None)
		if length is None:
			length = self.__len(r) - offset
		pdu = self.cla_byte + 'b0%04x%02x' % (offset, (min(256, length) & 0xff))
		return self._tp.send_apdu(pdu)

	def update_binary(self, ef, data, offset=0):
		if not hasattr(type(ef), '__iter__'):
			ef = [ef]
		self.select_file(ef)
		pdu = self.cla_byte + 'd6%04x%02x' % (offset, len(data)/2) + data
		return self._tp.send_apdu_checksw(pdu)

	def read_record(self, ef, rec_no):
		if not hasattr(type(ef), '__iter__'):
			ef = [ef]
		r = self.select_file(ef)
		rec_length = self.__record_len(r)
		pdu = self.cla_byte + 'b2%02x04%02x' % (rec_no, rec_length)
		return self._tp.send_apdu(pdu)

	def update_record(self, ef, rec_no, data, force_len=False):
		if not hasattr(type(ef), '__iter__'):
			ef = [ef]
		r = self.select_file(ef)
		if not force_len:
			rec_length = self.__record_len(r)
			if (len(data)/2 != rec_length):
				raise ValueError('Invalid data length (expected %d, got %d)' % (rec_length, len(data)/2))
		else:
			rec_length = len(data)/2
		pdu = (self.cla_byte + 'dc%02x04%02x' % (rec_no, rec_length)) + data
		return self._tp.send_apdu_checksw(pdu)

	def record_size(self, ef):
		r = self.select_file(ef)
		return self.__record_len(r)

	def record_count(self, ef):
		r = self.select_file(ef)
		return self.__len(r) // self.__record_len(r)

	def run_gsm(self, rand):
		if len(rand) != 32:
			raise ValueError('Invalid rand')
		self.select_file(['3f00', '7f20'])
		return self._tp.send_apdu(self.cla_byte + '88000010' + rand)

	def reset_card(self):
		return self._tp.reset_card()

	def verify_chv(self, chv_no, code):
		fc = rpad(b2h(code), 16)
		return self._tp.send_apdu_checksw(self.cla_byte + '2000' + ('%02X' % chv_no) + '08' + fc)
        
        def send_apdu(self, ins, p1 = '00', p2 = '00', data = "", parse_tlv = True, beautiful_print = True):
                ret = self._tp.send_apdu(self.cla_byte + ins + p1 + p2 + '%02x'%(len(data)/2) + data)
                if beautiful_print:
                        print(self._tp.apdu_to_string())
                        print("============================")
                if ret[1] == '6a82':
                        parse_tlv = False
                if parse_tlv:
			print(ret[0])
                        parsed = self.__parse_fcp(ret[0])
                        return ret, parsed

                return ret, None
        
        def send_apdu_without_length(self, ins, p1 = '00', p2 = '00', data = "", parse_tlv = False, beautiful_print = True):
                ret = self._tp.send_apdu(self.cla_byte + ins + p1 + p2  + data)
                if beautiful_print:
                        print(self._tp.apdu_to_string())
                        print("============================")
                if parse_tlv:
                        self.__parse_fcp(ret[0])

                return ret
                

                      
