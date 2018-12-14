import sys
import re

NUM_ARCH_REGS = 32
MIN_PHY_REGSS = 32    
#OUT_FILE = "pipeline"

CONFIGS = re.compile("^(\\d+),(\\d+)$")
INSTS = re.compile("^([RILS]),(\\d+),(\\d+),(\\d+)$")
OUT_FILE = 'pipeline'

def ParseFile (fileName):
    try:
        with open(fileName, 'r') as file:
            
            header = file.readline()

            configs = CONFIGS.match(header)
            if configs:
                (NumPhyReg, IssueWidth) = configs.group(1, 2)
                NumPhyReg = int(NumPhyReg)
                IssueWidth = int(IssueWidth)

                if NumPhyReg < MIN_PHY_REGSS:
                    sys.exit(1)

                yield (NumPhyReg, IssueWidth)
            else:
                sys.exit(1)

            for (index, line) in enumerate(file):
                configs = INSTS.match(line)
                if configs:
                    (Insts, op0, op1, op2) = configs.group(1, 2, 3, 4)

                    yield InstSet(index, Insts, int(op0), int(op1), int(op2))
                else:
                    print("Invalid InstSet: %s" % (line))
                    sys.exit(1)

    except IOError:
        sys.exit(1)

 
class InstSet (object):
    def __init__ (this, instrNumber, Insts, op0, op1, op2):
        this.instrNumber = instrNumber
        this.Insts = Insts

        if Insts == "I":
            this.operand = [op1]
            this.immidiate = op2
            this.op_result = op0
            this.M_access = False
        elif Insts == "R":
            this.operand = [op1, op2]
            this.immidiate = None
            this.op_result = op0
            this.M_access = False
        elif Insts == "L":
            this.operand = [op2]
            this.immidiate = op2
            this.op_result = op0
            this.M_access = True
        elif Insts == "S":
            this.operand = [op0, op2]
            this.immidiate = op1
            this.op_result = None
            this.M_access = True

        this.overwritten = None

        this.renamed = False

        this.FE = None
        this.DE = None
        this.RE = None
        this.DI = None
        this.IS = None
        this.WB = None
        this.CO = None

    def loadI (this):
        return this.Insts == "L"

    def storeI (this):
        return this.Insts == "S"

    def LS (this):
        return this.loadI() or this.storeI()

    def issueI (this):
        return this.IS is not None

    def wbI (this):
        return this.WB is not None

    def coI (this):
        return this.CO is not None

    def __repr__ (this):
        return "[InstSet %d: %s %s%s -> %s]" % (
            this.instrNumber,
            this.Insts,
            this.operand,
            " #%d" % (this.immidiate) if this.immidiate is not None else "",
            this.op_result
        )
        
class pipeline (object):
    def __init__ (this, width):
        this.queue = []

    def psuhQ (this, item):
        this.queue.append(item)

    def insertQ (this, item):
        this.queue.insert(0, item)

    def isEmpty (this):
        return len(this.queue) == 0

    def popQ (this):
        if this.isEmpty():
            raise TypeError("Pull from empty pipeline")

        return this.queue.pop(0)

    def __repr__ (this):
        return "[pipeline %s]" % (this.queue)


class regMap (object):
    def __init__ (this, num_arch_regs):
        this.num_arch_regs = num_arch_regs
        this.table = [None] * this.num_arch_regs

    def put (this, arch_reg_num, phy_reg_num):
        this.table[arch_reg_num] = phy_reg_num

    def get (this, arch_reg_num):
        return this.table[arch_reg_num]

    def __repr__ (this):
        return "[regMap %s]" % (this.table)


class FreeList (object):
    def __init__ (this, NumPhyRegs):
        this.freeList = list(range(NumPhyRegs))

    def isFree (this):
        return len(this.freeList)
    
    def getFreeReg (this):
        if not this.isFree():
            return TypeError("No free registers")
        
        return this.freeList.pop(0)

    def free (this, regNumber):
        this.freeList.append(regNumber)

    def __repr__ (this):
        return "[FreeList %s]" % (this.freeList)


class readyQ (object):
    def __init__ (this, NumPhyRegs):
        this.table = [True] * NumPhyRegs

    def isReady (this, regNumber):
        return this.table[regNumber]

    def ready (this, regNumber):
        this.table[regNumber] = True

    def clear (this, regNumber):
        this.table[regNumber] = False

    def __repr__ (this):
        return "[readyQ %s]" % (
            "".join(map(lambda x: "1" if x else "0", this.table))
        )


class lsQ (object):
    def __init__  (this):
        this.entries = []

    def append (this, instr):
        this.entries.append(instr)

    def remove (this, instr):
        this.entries.remove(instr)

    def canExecute (this, instr):
        for (index, otherInstr) in enumerate(this.entries):
            if (
                otherInstr.loadI()
                or (otherInstr.storeI() and index == 0)
            ):
                if otherInstr == instr:
                    return True

            if otherInstr.storeI():
                break

        return False

    def getExecutable (this):
        configs = []
        for (index, instr) in enumerate(this.entries):
            if (
                instr.loadI()
                or (instr.storeI() and index == 0)
            ):
                configs.append(instr)

            if instr.storeI():
                break

        return configs


class OutOfOrderScheduler (object):
    def __init__ (this, fileName):
        this.input = ParseFile(fileName)
        (NumPhyRegs, issueWidth) = next(this.input)
        this.NumPhyRegs = NumPhyRegs
        this.issueWidth = issueWidth

        this.fetching = True

        this.decodeQueue = pipeline(issueWidth)
        this.renameQueue = pipeline(issueWidth)
        this.dispatchQueue = pipeline(issueWidth)

        this.mapTable = regMap(NUM_ARCH_REGS)
        this.freeList = FreeList(NumPhyRegs)
        this.issueQueue = []
        this.reorderBuffer = []
        this.readyTable = readyQ(NumPhyRegs)
        this.lsq = lsQ()

        this.executing = []
        this.freeingRegisters = []

        for register in range(NUM_ARCH_REGS):
            this.mapTable.put(register, this.freeList.getFreeReg())

        this.instructions = []

        this.cycle = 0

        this.hasProgressed = True

        this.outFile = open(OUT_FILE, "w")

        this.isDebug = False

    def progress (this):
        this.hasProgressed = True

    def isScheduling (this):
        return (
            this.fetching
            or any(not instr.coI() for instr in this.instructions)
        )

    def schedule (this):

        this.fetching = True
        this.hasProgressed = True

        while this.isScheduling() and this.hasProgressed:
            this.hasProgressed = False

            this.commit()
            this.writeback()
            this.issue()
            this.dispatch()
            this.rename()
            this.decode()
            this.fetch()

            this.advanceCycle()

    def fetchInstSet (this):
        try:
            return next(this.input)
        except StopIteration:
            this.fetching = False
            return None

    def fetch (this):
        fetched = 0
        while this.fetching and fetched < this.issueWidth:
            instr = this.fetchInstSet()
            if instr is not None:
                this.debug("Fetched instruction")
                instr.FE = this.cycle
                this.instructions.append(instr)
                this.decodeQueue.psuhQ(instr)

                fetched += 1

                this.progress()

    def decode (this):
        while not this.decodeQueue.isEmpty():
            this.debug("Decoded instruction")
            instr = this.decodeQueue.popQ()
            instr.DE = this.cycle
            this.renameQueue.psuhQ(instr)

            this.progress()

    def rename (this):
        while not this.renameQueue.isEmpty():
            instr = this.renameQueue.popQ()

            physDependencies = list(map(
                lambda arch_reg_num: this.mapTable.get(arch_reg_num),
                instr.operand
            ))

            if instr.op_result is not None:
                if this.freeList.isFree():
                    physTarget = this.freeList.getFreeReg()

                    instr.overwritten = this.mapTable.get(instr.op_result)

                    this.mapTable.put(instr.op_result, physTarget)

                    instr.op_result = physTarget

                    this.readyTable.clear(physTarget)
                else:
                    this.renameQueue.insertQ(instr)
                    break

            this.debug("Renamed InstSet")

            instr.renamed = True
            instr.RE = this.cycle
            instr.operand = physDependencies
            this.dispatchQueue.psuhQ(instr)

            this.progress()

    def dispatch (this):
        while not this.dispatchQueue.isEmpty():
            this.debug("Dispatched instruction")

            instr = this.dispatchQueue.popQ()
            instr.DI = this.cycle
            this.issueQueue.append(instr)
            this.reorderBuffer.append(instr)

            if instr.M_access:
                this.lsq.append(instr)

            this.progress()

    def issue (this):
        issued = 0
        for instr in list(this.issueQueue):
            if issued >= this.issueWidth:
                break

            if this.isInstSetReady(instr):
                this.debug("Issued instruction")

                instr.IS = this.cycle
                this.issueQueue.remove(instr)

                if not instr.LS():
                    this.executing.append(instr)
                issued += 1

                this.progress()

    def writeback (this):
        for instr in this.executing:
            this.debug("Writeback instruction")

            instr.WB = this.cycle

            if instr.op_result:
                this.readyTable.ready(instr.op_result)

            this.progress()

        this.executing = []

        for instr in this.lsq.getExecutable():
            if instr.issueI():
                this.debug("Writeback LS instruction")

                instr.WB = this.cycle
                this.lsq.remove(instr)
                if instr.op_result is not None:
                    this.readyTable.ready(instr.op_result)

                this.progress()

    def commit (this):
        committed = 0
        while (
            len(this.reorderBuffer) > 0
            and this.reorderBuffer[0].wbI()
            and committed < this.issueWidth
        ):
            this.debug("Committed instruction")

            instr = this.reorderBuffer.pop(0)
            instr.CO = this.cycle

            if instr.overwritten is not None:
                this.freeingRegisters.append(instr.overwritten)

            this.progress()

    def isInstSetReady (this, instr):
        if not all(this.readyTable.isReady(dep) for dep in instr.operand):
            return False

        if instr.LS():
            return this.lsq.canExecute(instr)

        return True

    def advanceCycle (this):
        for freeReg in this.freeingRegisters:
            this.freeList.free(freeReg)
        this.freeingRegisters = []

        this.cycle += 1

        this.debug("Advanced cycle")

    def writeOutput (this):
        if this.isScheduling():
            this.outFile.write("")
            this.outFile.close()
            return

        for instr in this.instructions:
            this.outFile.write("%s,%s,%s,%s,%s,%s,%s\n" % (
                instr.FE,
                instr.DE,
                instr.RE,
                instr.DI,
                instr.IS,
                instr.WB,
                instr.CO,
            ))

        this.outFile.close()

    def debug (this, msg):
        if this.isDebug:
            print(msg)

    def __repr__ (this):
        return "[OutputOfOrderScheduler cycle=%d]" % (this.cycle)
        

def main (args):
    if len(args) != 2:
        sys.exit(1)
    (_, fileName) = args

    ooo = OutOfOrderScheduler(fileName)
    ooo.schedule()

    ooo.writeOutput()


if __name__ == "__main__":
    main(sys.argv)
