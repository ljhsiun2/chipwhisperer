import chipwhisperer as cw
from utils.utils import program_cw,disarm_target
from tqdm.notebook import trange
import struct
import time



def reboot_flush():
    scope.io.nrst = False
    time.sleep(0.05)
    scope.io.nrst = "high_z"
    time.sleep(0.05)
    target.flush()

def glitch_loop():
    target.simpleserial_write('g', bytearray([]))
    val = target.simpleserial_read_witherrors('r', 4, glitch_timeout=10)
    valid = val['valid']

    if valid:
        response = val['payload']
        raw_serial = val['full_response']
        error_code = val['rv']

    return response, raw_serial, error_code

scope, target = program_cw("./simpleserial-glitch-CWLITEARM.hex")

import chipwhisperer.common.results.glitch as glitch
import matplotlib.pylab as plt
gc = glitch.GlitchController(groups=["success", "reset", "normal"], parameters=["width", "offset"])
scope.glitch.ext_offset = 2

gc.set_range("width", 0, 20)
gc.set_range("offset", 0, 10)
gc.set_global_step([8, 1])
gc.display_stats()
scope.glitch.repeat = 10

scope.glitch.clk_src = "clkgen"
scope.glitch.output = "clock_xor"
scope.glitch.trigger_src = "ext_single"
scope.io.hs2 = "glitch"

scope.adc.timeout = 0.1

fig = plt.figure()
fig.canvas.draw()

# for glitch_setting in gc.glitch_values():
#     print("offset: {}", glitch_setting[1])
#     print("width: {}", glitch_setting[0])

reboot_flush()
broken = False
for glitch_setting in gc.glitch_values():
    scope.glitch.offset = glitch_setting[1]
    scope.glitch.width = glitch_setting[0]

    # print(scope.glitch)

    loff = scope.glitch.offset
    lwid = scope.glitch.width

    if scope.adc.state:
        print("Trigger still high!")
        gc.add("reset", (scope.glitch.width, scope.glitch.offset))

        plt.plot(lwid, loff, 'xr', alpha=1)
        fig.canvas.draw()
        reboot_flush()

    scope.arm()
    target.write("g\n")

    ret = scope.capture()
    val = target.simpleserial_read_witherrors('r', 4, glitch_timeout=10)

    # print(val)
    if ret:
        print("timeout - no trigger")
        gc.add("reset", (scope.glitch.width, scope.glitch.offset))
        plt.plot(scope.glitch.width, scope.glitch.offset, 'xr', alpha=1)
        fig.canvas.draw()
        reboot_flush()

    else:
        if val['valid'] is False:
            gc.add("reset", (scope.glitch.width, scope.glitch.offset))
            plt.plot(scope.glitch.width, scope.glitch.offset, 'xr', alpha=1)
            fig.canvas.draw()
        else:
            if val['payload'] is None:
                print(val['payload'])
                continue

            gcnt = struct.unpack("<I", val['payload'])[0]
            print(f"payload: {gcnt} (width: {lwid}, off: {loff})")

            if gcnt != 2500:
                broken = True
                gc.add("success", (scope.glitch.width, scope.glitch.offset))
                plt.plot(scope.glitch.width, scope.glitch.offset, '+g')
                fig.canvas.draw()
                print(val['payload'])
                print("success!")
            else:
                gc.add('normal', (scope.glitch.width, scope.glitch.offset))


gc.results.plot_2d(plotdots={"success":"+g", "reset":"xr", "normal":None})
fig.canvas.draw()

disarm_target()
plt.show()
