import chipwhisperer as cw

scope = cw.scope()
target = cw.target(scope)
scope.default_setup()

def program_cw(path):
    #scope = cw.scope(name='Lite')

    #target = cw.target(scope)
    #scope.default_setup()

    cw.program_target(scope, cw.programmers.STM32FProgrammer, path)
    return scope, target

def disarm_target():
    scope.dis()
    target.dis()
    print("Successfully disarmed")
