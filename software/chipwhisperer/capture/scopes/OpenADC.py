#!/usr/bin/python
# HIGHLEVEL_CLASSLOAD_FAIL_FUNC_WARN
# -*- coding: utf-8 -*-
#
# Copyright (c) 2013-2022, NewAE Technology Inc
# All rights reserved.
#
# Authors: Colin O'Flynn
#
# Find this and more at newae.com - this file is part of the chipwhisperer
# project, http://www.chipwhisperer.com
#
#=================================================
from chipwhisperer.logging import *
from chipwhisperer.hardware.naeusb.naeusb import NAEUSB
from .cwhardware import ChipWhispererDecodeTrigger, ChipWhispererDigitalPattern, ChipWhispererExtra, \
     ChipWhispererSAD, ChipWhispererHuskyClock
from .cwhardware.ChipWhispererHuskyMisc import XilinxDRP, XilinxMMCMDRP, LEDSettings, HuskyErrors, \
        USERIOSettings, XADCSettings, LASettings, ADS4128Settings
from ._OpenADCInterface import OpenADCInterface, HWInformation, GainSettings, TriggerSettings, ClockSettings

from .cwhardware.ChipWhispererSAM3Update import SAMFWLoader
from .openadc_interface.naeusbchip import OpenADCInterface_NAEUSBChip
from ...common.utils import util
from ...common.utils.util import dict_to_str, DelayedKeyboardInterrupt
from collections import OrderedDict
import time
import numpy as np
from ..api.cwcommon import ChipWhispererCommonInterface

from typing import List, Dict, Any



ADDR_GLITCH1_DRP_ADDR  = 62
ADDR_GLITCH1_DRP_DATA  = 63
ADDR_GLITCH2_DRP_ADDR  = 64
ADDR_GLITCH2_DRP_DATA  = 65
ADDR_GLITCH1_DRP_RESET = 79
ADDR_GLITCH2_DRP_RESET = 80
ADDR_LA_DRP_ADDR       = 68
ADDR_LA_DRP_DATA       = 69
ADDR_LA_DRP_RESET      = 74

CODE_READ              = 0x80
CODE_WRITE             = 0xC0

class OpenADC(util.DisableNewAttr, ChipWhispererCommonInterface):

    """OpenADC scope object.

    This class contains the public API for the OpenADC hardware, including the
    ChipWhisperer Lite/ CW1200 Pro boards. It includes specific settings for
    each of these devices.

    To connect to one of these devices, the easiest method is::

        import chipwhisperer as cw
        scope = cw.scope(type=scopes.OpenADC)

    Some sane default settings are available via::

        scope.default_setup()

    This code will automatically detect an attached ChipWhisperer device and
    connect to it.

    For more help about scope settings, try help() on each of the ChipWhisperer
    scope submodules (scope.gain, scope.adc, scope.clock, scope.io,
    scope.trigger, and scope.glitch):

     *  :attr:`scope.gain <.OpenADC.gain>`
     *  :attr:`scope.adc <.OpenADC.adc>`
     *  :attr:`scope.clock <.OpenADC.clock>`
     *  :attr:`scope.io <.OpenADC.io>`
     *  :attr:`scope.trigger <.OpenADC.trigger>`
     *  :attr:`scope.glitch <.OpenADC.glitch>`
     *  :meth:`scope.default_setup <.OpenADC.default_setup>`
     *  :meth:`scope.con <.OpenADC.con>`
     *  :meth:`scope.dis <.OpenADC.dis>`
     *  :meth:`scope.arm <.OpenADC.arm>`
     *  :meth:`scope.get_last_trace <.OpenADC.get_last_trace>`
     *  :meth:`scope.get_serial_ports <.OpenADC.get_serial_ports>`

    If you have a CW1200 ChipWhisperer Pro, you have access to some additional features:

     * :attr:`scope.SAD <.OpenADC.SAD>`
     * :attr:`scope.DecodeIO <.OpenADC.DecodeIO>`
     * :attr:`scope.adc.stream_mode (see scope.adc for more information)`
    """

    _name = "ChipWhisperer/OpenADC"

    def __init__(self):
        # self.qtadc = openadc_qt.OpenADCQt()
        # self
        super().__init__()
        self.enable_newattr()

        # Bonus Modules for ChipWhisperer
        self.advancedSettings = None
        self.advancedSAD = None
        self.digitalPattern = None

        self._is_connected = False
        self.data_points = []
        self._is_husky = False

        # self.scopetype = OpenADCInterface_NAEUSBChip(self.qtadc)
        self.connectStatus = True
        # self.disable_newattr()

    def _getFWPy(self) -> List[int]:
        cw_type = self._getCWType()
        if cw_type == "cwlite":
            from ...hardware.firmware.cwlite import fwver
        elif cw_type == "cw1200":
            from ...hardware.firmware.cw1200 import fwver # type: ignore
        elif cw_type == "cwhusky":
            from ...hardware.firmware.cwhusky import fwver # type: ignore
        else:
            raise ValueError('Unknown cw_type: %s' % cw_type)
        return fwver

    def reload_fpga(self, bitstream=None, reconnect=True, prog_speed=1E6):
        """(Re)loads a FPGA bitstream (even if already configured).

        Will cause a reconnect event, all settings become default again.
        If no bitstream specified default is used based on current
        configuration settings.
        """
        self.scopetype.reload_fpga(bitstream, prog_speed=1E6)
        self.dis()
        self.con(self._saved_sn)

    def _getNAEUSB(self) -> NAEUSB:
        return self.scopetype.ser

    def enable_MPSSE(self, enable=True):
        sn = self.sn
        if enable:
            self.io.cwe.setAVRISPMode(1)
        else:
            self.io.cwe.setAVRISPMode(0)
        super().enable_MPSSE(enable)

        if enable and (not self._is_husky):
            # non husky needs to be setup after MPSSE is setup
            for i in range(10):
                time.sleep(0.50)
                try:
                    self.con(sn=sn)
                    break
                except:
                    pass
            try:
                self.default_setup()
            except:
                raise IOError("Could not reconnect to ChipWhisperer. \
                    Try connecting manually and running \
                        scope.default_setup(); scope.io.cwe.setAVRISPMode(1)")
            self.io.cwe.setAVRISPMode(1)
            self.dis()
    
    def finish_mpsse_setup(self, set_defaults=True):
        if set_defaults:
            self.default_setup()
        self.io.cwe.setAVRISPMode(1)

    def default_setup(self):
        """Sets up sane capture defaults for this scope

         *  25dB gain
         *  5000 capture samples
         *  0 sample offset
         *  rising edge trigger
         *  7.37MHz clock output on hs2
         *  4*7.37MHz ADC clock
         *  tio1 = serial rx
         *  tio2 = serial tx
         *  CDC settings change off

        .. versionadded:: 5.1
            Added default setup for OpenADC
        """
        self.gain.db = 25
        self.adc.samples = 5000
        self.adc.offset = 0
        self.adc.basic_mode = "rising_edge"
        self.clock.clkgen_freq = 7.37e6
        self.trigger.triggers = "tio4"
        self.io.tio1 = "serial_rx"
        self.io.tio2 = "serial_tx"
        self.io.hs2 = "clkgen"

        self.io.cdc_settings = 0

        count = 0
        if self._is_husky:
            self.clock.clkgen_src = 'system'
            self.clock.clkgen_freq = 7.37e6
            self.clock.adc_mul = 4
            while not self.clock.clkgen_locked:
                count += 1
                self.clock.reset_dcms()
                if count > 10:
                    raise OSError("Could not lock PLL. Try rerunning this function or calling scope.pll.reset(): {}".format(self))

            # these are the power-up defaults, but just in case e.g. test script left these on:
            self.adc.test_mode = False
            self.ADS4128.mode = 'normal'
            self.glitch.enabled = False
            self.LA.enabled = False


        else:
            self.clock.adc_src = "clkgen_x4"
            while not self.clock.clkgen_locked:
                self.clock.reset_dcms()
                time.sleep(0.05)
                count += 1

                if count == 5:
                    scope_logger.info("Could not lock clock for scope. This is typically safe to ignore. Reconnecting and retrying...")
                    self.dis()
                    time.sleep(0.25)
                    self.con()
                    time.sleep(0.25)
                    self.gain.db = 25
                    self.adc.samples = 5000
                    self.adc.offset = 0
                    self.adc.basic_mode = "rising_edge"
                    self.clock.clkgen_freq = 7.37e6
                    self.trigger.triggers = "tio4"
                    self.clock.adc_src = "clkgen_x4"
                    self.io.tio1 = "serial_rx"
                    self.io.tio2 = "serial_tx"
                    self.io.hs2 = "clkgen"
                    self.clock.adc_src = "clkgen_x4"

                if count > 10:
                    raise OSError("Could not lock DCM. Try rerunning this function or calling scope.clock.reset_dcms(): {}".format(self))

    def dcmTimeout(self):
        if self._is_connected:
            try:
                self.sc.getStatus()
            except Exception as e:
                self.dis()
                raise e

    def getCurrentScope(self) -> OpenADCInterface_NAEUSBChip:
        return self.scopetype

    def setCurrentScope(self, scope : OpenADCInterface_NAEUSBChip):
        self.scopetype = scope

    def _getCWType(self) -> str:
        """Find out which type of ChipWhisperer this device is.

        Returns:
            One of the following:
             -  ""
             -  "cwlite"
             -  "cw1200"
             -  "cwrev2"
        """
        hwInfoVer = self.sc.hwInfo.versions()[2]
        if "ChipWhisperer" in hwInfoVer:
            if "Lite" in hwInfoVer:
                return "cwlite"
            elif "CW1200" in hwInfoVer:
                return "cw1200"
            elif "Husky" in hwInfoVer:
                return "cwhusky"
            else:
                return "cwrev2"
        return ""

    def get_name(self):
        """ Gets the name of the attached scope

        Returns:
            'ChipWhisperer Lite' if a Lite, 'ChipWhisperer Pro' if a Pro
        """
        name = self._getCWType()
        if name == "cwlite":
            return "ChipWhisperer Lite"
        elif name == "cw1200":
            return "ChipWhisperer Pro"
        elif name == "cwhusky":
            return "ChipWhisperer Husky"

    @property
    def fpga_buildtime(self):
        """When the FPGA bitfile was generated. Husky only.
        """
        if not self._is_husky:
            raise ValueError("For CW-Husky only.")
        return self.sc.hwInfo.get_fpga_buildtime()

    def reset_fpga(self):
        """Reset Husky FPGA. This causes all FPGA-based settings to return to their default values.
        """
        if not self._is_husky:
            raise ValueError("For CW-Husky only.")
        self.sc.reset_fpga()
        self.adc._clear_caches()
        self.sc._clear_caches()
        self.gain._clear_caches()
        self.ADS4128.set_defaults()


    def con(self, sn=None, idProduct=None, bitstream=None, force=False, prog_speed=10E6, **kwargs):
        """Connects to attached chipwhisperer hardware (Lite, Pro, or Husky)

        Args:
            sn (str): The serial number of the attached device. Does not need to
                be specified unless there are multiple devices attached.
            idProduct (int): The product ID of the ChipWhisperer. If None, autodetects product ID. Optional.
            bitstream (str): Path to bitstream to program. If None, programs default bitstream. Optional.
            force (bool): Force reprogramming of bitstream. If False, only program bitstream if no bitstream
                is currently programmed. Optional.

        Returns:
            True if connection is successful, False otherwise

        .. versionchanged:: 5.5
            Added idProduct, bitstream, and force parameters.
        """
        self._read_only_attrs = []
        self._saved_sn = sn
        self.scopetype = OpenADCInterface_NAEUSBChip()

        self.scopetype.con(sn, idProduct, bitstream, force, prog_speed, **kwargs)
        self.sc = OpenADCInterface(self.scopetype.ser) # important to instantiate this before other FPGA components, since this does an FPGA reset
        self.hwinfo = HWInformation(self.sc)
        cwtype = self._getCWType()
        if cwtype == "cwhusky":
            self.sc._is_husky = True
        self.sc._setReset(True)
        self.sc._setReset(False)

        self.adc = TriggerSettings(self.sc)
        self.gain = GainSettings(self.sc, self.adc)

        self.pll = None
        self.advancedSettings = ChipWhispererExtra.ChipWhispererExtra(cwtype, self.scopetype, self.sc)
        self.glitch_drp1 = None
        self.glitch_drp2 = None
        self.la_drp = None
        self.glitch_mmcm1 = None
        self.glitch_mmcm2 = None
        self.la_mmcm = None

        util.chipwhisperer_extra = self.advancedSettings

        if cwtype == "cw1200":
            self.SAD = ChipWhispererSAD.ChipWhispererSAD(self.sc)
            self.decode_IO = ChipWhispererDecodeTrigger.ChipWhispererDecodeTrigger(self.sc)

        if cwtype == "cwhusky":
            # self.pll = ChipWhispererHuskyClock.CDCI6214(self.sc)
            self._fpga_clk = ClockSettings(self.sc, hwinfo=self.hwinfo)
            self.glitch_drp1 = XilinxDRP(self.sc, ADDR_GLITCH1_DRP_DATA, ADDR_GLITCH1_DRP_ADDR, ADDR_GLITCH1_DRP_RESET)
            self.glitch_drp2 = XilinxDRP(self.sc, ADDR_GLITCH2_DRP_DATA, ADDR_GLITCH2_DRP_ADDR, ADDR_GLITCH2_DRP_RESET)
            self.la_drp = XilinxDRP(self.sc, ADDR_LA_DRP_DATA, ADDR_LA_DRP_ADDR, ADDR_LA_DRP_RESET)
            self.glitch_mmcm1 = XilinxMMCMDRP(self.glitch_drp1)
            self.glitch_mmcm2 = XilinxMMCMDRP(self.glitch_drp2)
            self.la_mmcm = XilinxMMCMDRP(self.la_drp)
            self.clock = ChipWhispererHuskyClock.ChipWhispererHuskyClock(self.sc, \
                self._fpga_clk, self.glitch_mmcm1, self.glitch_mmcm2)
            self.ADS4128 = ADS4128Settings(self.sc)
            self.XADC = XADCSettings(self.sc)
            self.LEDs = LEDSettings(self.sc)
            self.errors = HuskyErrors(self.sc, self.XADC, self.adc, self.clock)
            self.LA = LASettings(self.sc, self.la_mmcm)
            self.userio = USERIOSettings(self.sc)
        else:
            self.clock = ClockSettings(self.sc, hwinfo=self.hwinfo)


        if cwtype == "cw1200":
            self.adc._is_pro = True
        if cwtype == "cwlite":
            self.adc._is_lite = True
        elif cwtype == "cwhusky":
            self._is_husky = True
            self.adc._is_husky = True
            self.gain._is_husky = True
            self._fpga_clk._is_husky = True
            self.sc._is_husky = True
            self.adc.bits_per_sample = 12
        if self.advancedSettings:
            self.io = self.advancedSettings.cwEXTRA.gpiomux
            self.trigger = self.advancedSettings.cwEXTRA.triggermux
            self.glitch = self.advancedSettings.glitch.glitchSettings
            if cwtype == 'cwhusky':
                # TODO: cleaner way to do this?
                self.glitch.pll = self.clock.pll
                self.clock.pll._glitch = self.glitch
                self.advancedSettings.glitch.pll = self.clock.pll
            if cwtype == "cw1200":
                self.trigger = self.advancedSettings.cwEXTRA.protrigger

        if cwtype == "cwhusky":
            # these are the power-up defaults, but just in case e.g. test script left these on:
            self.adc.test_mode = False
            self.ADS4128.mode = 'normal'
            self.glitch.enabled = False
            self.LA.enabled = False

        module_list = [x for x in self.__dict__ if isinstance(self.__dict__[x], util.DisableNewAttr)]
        self.add_read_only(module_list)
        self.disable_newattr()
        self._is_connected = True
        self.connectStatus = True

        return True

    def dis(self):
        """Disconnects the current scope object.

        Returns:
            True if the disconnection was successful, False otherwise.
        """
        self._read_only_attrs = [] # disable read only stuff
        if self.scopetype is not None:
            self.scopetype.dis()
            if self.advancedSettings is not None:
                self.advancedSettings = None
                util.chipwhisperer_extra = None

            if self.advancedSAD is not None:
                self.advancedSAD = None

            if self.digitalPattern is not None:
                self.digitalPattern = None

        if hasattr(self.scopetype, "ser") and hasattr(self.scopetype.ser, "_usbdev"):
            self.sc.usbcon = None

        self.enable_newattr()
        self._is_connected = False
        self.connectStatus = False
        return True

    def arm(self):
        """Setup scope to begin capture/glitching when triggered.

        The scope must be armed before capture or glitching (when set to
        'ext_single') can begin.

        Raises:
           OSError: Scope isn't connected.
           Exception: Error when arming. This method catches these and
               disconnects before reraising them.
        """
        if self._is_connected is False:
            raise OSError("Scope is not connected. Connect it first...")
        # with DelayedKeyboardInterrupt():
        try:
            self.advancedSettings.armPreScope()

            self.sc.arm()

            self.advancedSettings.armPostScope()

            # For Husky, scope.adc parameters must be cached before startCaptureThread turns on fast read mode,
            # because we won't be able to read them from the FPGA once fast read mode is turned on:
            if self._is_husky:
                self.adc._update_caches()

            self.sc.startCaptureThread()
        except Exception:
            self.dis()
            raise

    def _capture_read(self, num_points=None):
        if num_points is None:
            num_points = self.adc.samples
        scope_logger.debug("Expecting {} points".format(num_points))

        self.data_points = self.sc.readData(num_points)

        scope_logger.debug("Read {} datapoints".format(len(self.data_points)))
        if (self.data_points is None) or (len(self.data_points) != num_points):
            scope_logger.error("Received fewer points than expected: {} vs {}".format(len(self.data_points), num_points))
            return True
        return False


    def capture(self, poll_done : bool =False) -> bool:
        """Captures trace. Scope must be armed before capturing.

        Args:
            poll_done: Supported by Husky only. Poll
                Husky to find out when it's done capturing, instead of
                calculating the capture time based on the capture parameters.
                Can result in slightly faster captures when the number of
                samples is high. Defaults to False.
        Returns:
           True if capture timed out, false if it didn't.

        Raises:
           IOError: Unknown failure.

        .. versionchanged:: 5.6.1
            Added poll_done parameter for Husky

        """
        if self._is_husky and self.adc.segments > 1 and self.adc.presamples and self.adc.samples % 3:
            raise ValueError('When using segments with presamples, the number of samples per segment (scope.adc.samples) must be a multiple of 3.')

        if self._is_husky and (self.adc.decimate > 1) and (self.adc.presamples or self.adc.segments > 1):
            raise ValueError('When decimate (%d) is used, presamples or segments cannot be used.' % self.adc.decimate)

        if self._is_husky and (self.adc.segments > 1) and (self.adc.samples * self.adc.segments > self.adc.oa.hwMaxSegmentSamples) and (not self.adc.stream_mode):
            raise ValueError('When using segments and stream mode is disabled, the maximum total number of samples is %d.' % self.adc.oa.hwMaxSegmentSamples)

        if self.adc.stream_mode and (not self._is_husky):
            a = self.sc.capture(None)
        else:
            a = self.sc.capture(self.adc.offset, self.clock.adc_freq, self.adc.samples, self.adc.segments, self.adc.segment_cycles, poll_done)

        # _capture_read() must be given the total number of samples to read; in the case of Husky, self.adc.samples
        # is the number of samples *per segment*, so adjust accordingly:
        if self._is_husky:
            samples = self.adc.samples * self.adc.segments
        else:
            samples = self.adc.samples
        b = self._capture_read(samples)
        return a or b

    def get_last_trace(self, as_int : bool=False) -> np.ndarray:
        """Return the last trace captured with this scope.

        Can return traces as floating point values (:code:`as_int=False`)
        or as integers.

        Floating point values are scaled and shifted to be between -0.5 and 0.5.

        Integer values are raw readings from the ChipWhisperer ADC. The ChipWhisperer-Lite
        has a 10-bit ADC, the Nano has an 8-bit ADC, and the Husky can read either
        8-bits or 12-bits of ADC data.

        Args:
            as_int: If False, return trace as a float. Otherwise, return as an int.

        Returns:
           Numpy array of the last capture trace.

        .. versionchanged:: 5.6.1
            Added as_int parameter
        """
        if as_int:
            return self.sc._int_data
        return self.data_points

    getLastTrace = util.camel_case_deprecated(get_last_trace)

    def capture_segmented(self):
        """Captures trace in segment mode, returns as many segments as buffer holds.

        Timeouts not handled yet properly (function will lock). Be sure you are generating
        enough triggers for segmented mode.

        Returns:
           True if capture timed out, false if it didn't.

        Raises:
           IOError: Unknown failure.

        .. versionadded:: 5.5
            Added segmented capture (requires custom bitstream)
        """

        if self.adc.fifo_fill_mode != "segment":
            raise IOError("ADC is not in 'segment' mode - aborting.")

        if self._is_husky:
            scope_logger.warning("Not intended for Husky -- just use a regular capture.")

        with DelayedKeyboardInterrupt():
            max_fifo_size = self.adc.oa.hwMaxSamples
            #self.adc.offset should maybe be ignored - passing for now but untested
            timeout = self.sc.capture(self.adc.offset, self.clock.adc_freq, max_fifo_size)
            timeout2 = self._capture_read(max_fifo_size-256)

            return timeout or timeout2

    def get_last_trace_segmented(self):
        """Return last trace assuming it was captued with segmented mode.

        NOTE: The length of each returned trace is 1 less sample than requested.

        Returns:
            2-D numpy array of the last captured traces.

        .. versionadded:: 5.5
            Added segmented capture (requires custom bitstream)
        """

        seg_len = self.adc.samples-1
        num_seg = int(len(self.data_points) / seg_len)

        return np.reshape(self.data_points[:num_seg*seg_len], (num_seg, seg_len))

    def _dict_repr(self) -> dict:
        rtn : Dict[str, Any] = {}
        rtn['sn'] = self.sn
        if self._is_husky:
            rtn['fpga_buildtime'] = self.fpga_buildtime
        rtn['fw_version'] = self.fw_version
        rtn['gain']    = self.gain._dict_repr()
        rtn['adc']     = self.adc._dict_repr()
        rtn['clock']   = self.clock._dict_repr()
        rtn['trigger'] = self.trigger._dict_repr()
        rtn['io']      = self.io._dict_repr()
        rtn['glitch']  = self.glitch._dict_repr()
        if self._getCWType() == "cw1200":
            rtn['SAD'] = self.SAD._dict_repr()
            rtn['decode_IO'] = self.decode_IO._dict_repr()
        if self._is_husky:
            rtn['ADS4128'] = self.ADS4128._dict_repr()
            # rtn['pll'] = self.pll._dict_repr()
            rtn['LA'] = self.LA._dict_repr()
            rtn['XADC'] = self.XADC._dict_repr()
            rtn['userio'] = self.userio._dict_repr()
            rtn['LEDs'] = self.LEDs._dict_repr()
            rtn['errors'] = self.errors._dict_repr()

        return rtn

    def __repr__(self):
        # Add some extra information about ChipWhisperer type here
        if self._is_connected:
            ret = "%s Device\n" % self._getCWType()
            return ret + dict_to_str(self._dict_repr())
        else:
            ret = "ChipWhisperer/OpenADC device (disconnected)"
            return ret

    def __str__(self):
        return self.__repr__()

    def upgrade_firmware(self):
        """Attempt a firmware upgrade. See https://chipwhisperer.readthedocs.io/en/latest/firmware.html for more information.

        .. versionadded:: 5.6.1
            Improved programming interface
        """
        prog = SAMFWLoader(self)
        prog.auto_program()

    def fpga_reg_read(self, addr, numbytes):
        """Convenience method to read an FPGA register. Intended for debug/development.
        Args:
            addr (int): FPGA address to read.
            numbytes (int): number of bytes to read.

        Returns:
            read result: list of <numbytes> bytes.

        .. versionadded:: 5.6.1
        """
        return list(self.sc.sendMessage(CODE_READ, addr, maxResp=numbytes))

    def fpga_reg_write(self, addr, listofbytes):
        """Convenience method to write an FPGA register. Intended for debug/development.
        Args:
            addr (int): FPGA address to write.
            listofbytes (int array): list of bytes to write.

        .. versionadded:: 5.6.1
        """
        return self.sc.sendMessage(CODE_WRITE, addr, listofbytes)


