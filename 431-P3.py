import sys
import re

# constants
COUNT_ARCH_REGS = 32
MIN_PHYS_REGS = 32    # there must be MORE than this number of physical registers
OUTPUT_FILE = "out.txt"

# some regular expressions for parsing the input file
HEADER_FORMAT = re.compile("^(\\d+),(\\d+)$")
INSTRUCTION_FORMAT = re.compile("^([RILS]),(\\d+),(\\d+),(\\d+)$")


# generator function which reads the file and produces it's decoded contents
# the first value is a 2-tuple of the count of physical registers and the issue width
# the rest of the values are decoded instructions
def inputReader (fileName):
    try:
        # open the file (remains open until all instructions are read)
        with open(fileName, 'r') as file:
            # read header
            headerLine = file.readline()

            # parse the header
            result = HEADER_FORMAT.match(headerLine)
            if result:
                (countPhysReg, fetchWidth) = result.group(1, 2)
                countPhysReg = int(countPhysReg)
                fetchWidth = int(fetchWidth)

                # check if the number of physical registers is enough (> MIN_PHYS_REGS)
                if countPhysReg <= MIN_PHYS_REGS:
                    print("Invalid number of physical registers: %d" % (countPhysReg))

                    # empty file will be written, since out.txt is opened for write at beginning

                    # quit
                    sys.exit(1)

                # yield header information
                yield (countPhysReg, fetchWidth)
            else:
                # bad header, quit
                print("Invalid Header: %s" % (headerLine))
                sys.exit(1)

            # iterate through lines, yielding decoded instructions
            for (index, line) in enumerate(file):

                # parse instruction
                result = INSTRUCTION_FORMAT.match(line)
                if result:
                    (instrType, arg0, arg1, arg2) = result.group(1, 2, 3, 4)

                    # create, decode, and yield instruction
                    yield Instruction(index, instrType, int(arg0), int(arg1), int(arg2))
                else:
                    # bad instruction, quit
                    print("Invalid Instruction: %s" % (line))
                    sys.exit(1)

    except IOError:
        # file did not exist, quit
        print("File not found")
        sys.exit(1)


# Represent an instruction, may be either renamed or not
# holds information about the instruction, as well as what cycles it completed various pipeline stages
class Instruction (object):
    def __init__ (this, instrNumber, instrType, arg0, arg1, arg2):
        # which instruction it is, starting from 0
        this.instrNumber = instrNumber
        # type of instruction, one of [R, I, L, S]
        this.instrType = instrType

        # set up various information depending on type of instruction
        if instrType == "R":
            this.dependencies = [arg1, arg2]
            this.imm = None
            this.target = arg0
            this.doesMemory = False
        elif instrType == "I":
            this.dependencies = [arg1]
            this.imm = arg2
            this.target = arg0
            this.doesMemory = False
        elif instrType == "L":
            this.dependencies = [arg2]
            this.imm = arg2
            this.target = arg0
            this.doesMemory = True
        elif instrType == "S":
            this.dependencies = [arg0, arg2]
            this.imm = arg1
            this.target = None
            this.doesMemory = True

        # register that was overwritten, so it can be freed at commit
        this.overwritten = None

        # whether or not this instruction has been renamed
        this.renamed = False

        # what cycle the instruction completed various stages
        this.fetchCycle = None
        this.decodeCycle = None
        this.renameCycle = None
        this.dispatchCycle = None
        this.issueCycle = None
        this.writebackCycle = None
        this.commitCycle = None

    def isLoad (this):
        return this.instrType == "L"

    def isStore (this):
        return this.instrType == "S"

    def isLoadOrStore (this):
        return this.isLoad() or this.isStore()

    def hasIssued (this):
        return this.issueCycle is not None

    def hasWroteback (this):
        return this.writebackCycle is not None

    def hasCommitted (this):
        return this.commitCycle is not None

    def __repr__ (this):
        return "[Instruction %d: %s %s%s -> %s]" % (
            this.instrNumber,
            this.instrType,
            this.dependencies,
            " #%d" % (this.imm) if this.imm is not None else "",
            this.target
        )


# Basically, just a simple queue implementation on top of Python list
# used between pipeline stages in some instances
class PipelineQueue (object):
    def __init__ (this, width):
        this.queue = []

    def push (this, item):
        this.queue.append(item)

    def pushBack (this, item):
        this.queue.insert(0, item)

    def isEmpty (this):
        return len(this.queue) == 0

    def pull (this):
        if this.isEmpty():
            raise TypeError("Pull from empty pipeline")

        return this.queue.pop(0)

    def __repr__ (this):
        return "[PipelineQueue %s]" % (this.queue)


# Holds current mapping from architected register
class MapTable (object):
    def __init__ (this, countArchRegs):
        this.countArchRegs = countArchRegs
        this.table = [None] * this.countArchRegs

    def put (this, archRegNumber, physRegNumber):
        this.table[archRegNumber] = physRegNumber

    def get (this, archRegNumber):
        return this.table[archRegNumber]

    def __repr__ (this):
        return "[MapTable %s]" % (this.table)


# Holds the list of currently free phyical registers
# It's also essentially a queue
class FreeList (object):
    def __init__ (this, countPhysRegs):
        this.freeList = list(range(countPhysRegs))

    def hasAny (this):
        return len(this.freeList)
    
    def getFreeReg (this):
        if not this.hasAny():
            return TypeError("No free registers")
        
        return this.freeList.pop(0)

    def free (this, regNumber):
        this.freeList.append(regNumber)

    def __repr__ (this):
        return "[FreeList %s]" % (this.freeList)


# Holds an array of the ready bits corresponding to each physical register
# Implementation note: rather than tacking on a ready bit to each dependency in each instruction
#   and broadcasting when something becomes ready to all instruction in the IQ,
#   all instructions reference this data structure to see if the ready (no duplication of the bit)
class ReadyTable (object):
    def __init__ (this, countPhysRegs):
        this.table = [True] * countPhysRegs

    def isReady (this, regNumber):
        return this.table[regNumber]

    def ready (this, regNumber):
        this.table[regNumber] = True

    def clear (this, regNumber):
        this.table[regNumber] = False

    def __repr__ (this):
        return "[ReadyTable %s]" % (
            "".join(map(lambda x: "1" if x else "0", this.table))
        )


# Conservative LSQ
# Main job is to determine which instructions can possibly execute this cycle through bypassing
# whether or not or the inputs are ready (that is Scheduler's responsibility)
class ConservativeLsq (object):
    def __init__  (this):
        this.entries = []

    def append (this, instr):
        this.entries.append(instr)

    def remove (this, instr):
        this.entries.remove(instr)

    def canExecute (this, instr):
        # assuming everything else is set-up...
        #   can the given instr execute with regards to conservative ordering
        for (index, otherInstr) in enumerate(this.entries):
            if (
                otherInstr.isLoad()
                or (otherInstr.isStore() and index == 0)
            ):
                # yes this can go
                if otherInstr == instr:
                    return True

            if otherInstr.isStore():
                # nothing beyond this can go
                break

        return False

    def getExecutable (this):
        # assuming everything else is set-up...
        #   get LSQ entries that would be executable immediately
        result = []
        for (index, instr) in enumerate(this.entries):
            if (
                instr.isLoad()
                or (instr.isStore() and index == 0)
            ):
                result.append(instr)

            if instr.isStore():
                break

        return result


# Does almost everything in terms of scheduling
class OutOfOrderScheduler (object):
    def __init__ (this, fileName):
        # fetches from the input file, header information and instructions
        this.input = inputReader(fileName)
        # read header information
        (countPhysRegs, issueWidth) = next(this.input)
        this.countPhysRegs = countPhysRegs
        this.issueWidth = issueWidth

        # whether there may still be instructions to fetch from the input
        this.fetching = True

        # queues between stages (e.g. decodeQueue is between fetch and decode stage)
        this.decodeQueue = PipelineQueue(issueWidth)
        this.renameQueue = PipelineQueue(issueWidth)
        this.dispatchQueue = PipelineQueue(issueWidth)

        # many of the hardware structures
        this.mapTable = MapTable(COUNT_ARCH_REGS)
        this.freeList = FreeList(countPhysRegs)
        this.issueQueue = []
        this.reorderBuffer = []
        this.readyTable = ReadyTable(countPhysRegs)
        this.lsq = ConservativeLsq()

        # queue between IQ and writeback
        this.executing = []
        # registers that are freed during commit, waiting to go back in free list at end of cycle
        this.freeingRegisters = []

        # set up initial mapping of from architected register to physical registers
        for register in range(COUNT_ARCH_REGS):
            this.mapTable.put(register, this.freeList.getFreeReg())

        # overall list of instructions fetched (held so that they can be written back)
        this.instructions = []

        # the current cycle
        this.cycle = 0

        # used internally to ensure the scheduler is still making progress, not caught in an infinite loop
        this.hasProgressed = True

        # the output file, opened here so that any exit conditions (other than missing file name) will write a blank file
        this.outFile = open(OUTPUT_FILE, "w")

        # flag to set, which prints out debug information
        this.isDebug = False

    # mark that progress has been done this cycle
    def progress (this):
        this.hasProgressed = True

    # check whether scheduling is still going on (fetching or un-committed instructions remaining)
    def isScheduling (this):
        return (
            this.fetching
            or any(not instr.hasCommitted() for instr in this.instructions)
        )

    # the primary scheduling loop
    # does each stage in reverse order for each cycle
    # they are done in reverse order, so passing from one phase to another takes at least one cycle
    def schedule (this):

        # set-up some variables
        this.fetching = True
        this.hasProgressed = True

        # main loop, stops after scheduling completes or no progress is made
        while this.isScheduling() and this.hasProgressed:
            # means to make sure, the program isn't caught in an infinite loop, start with no progress
            this.hasProgressed = False

            # stages in reverse order
            this.commit()
            this.writeback()
            this.issue()
            this.dispatch()
            this.rename()
            this.decode()
            this.fetch()

            # go to next cycle
            this.advanceCycle()

    # fetch an instruction from the file
    # handle when the instructions run out
    def fetchInstruction (this):
        try:
            return next(this.input)
        except StopIteration:
            this.fetching = False
            return None

    # fetch up to issueWidth instructions into decode queue
    def fetch (this):
        fetched = 0
        while this.fetching and fetched < this.issueWidth:
            instr = this.fetchInstruction()
            if instr is not None:
                this.debug("Fetched instruction")
                instr.fetchCycle = this.cycle
                this.instructions.append(instr)
                this.decodeQueue.push(instr)

                fetched += 1

                # signal progress
                this.progress()

    # decode fetched instruction into rename queue
    def decode (this):
        # not much to do here, since instructions are pre-decoded
        # just drain decode queue into rename queue
        while not this.decodeQueue.isEmpty():
            this.debug("Decoded instruction")
            instr = this.decodeQueue.pull()
            instr.decodeCycle = this.cycle
            this.renameQueue.push(instr)

            # signal progress
            this.progress()

    # rename instructions and move to dispatch queue
    def rename (this):
        while not this.renameQueue.isEmpty():
            # get next instruction
            instr = this.renameQueue.pull()

            # rename dependencies
            physDependencies = list(map(
                lambda archRegNumber: this.mapTable.get(archRegNumber),
                instr.dependencies
            ))

            # if this has a target try to free register from free list
            if instr.target is not None:
                if this.freeList.hasAny():
                    # found free register
                    physTarget = this.freeList.getFreeReg()

                    # store overwritten so it can be freed later
                    instr.overwritten = this.mapTable.get(instr.target)

                    # update map table
                    this.mapTable.put(instr.target, physTarget)

                    # rename target
                    instr.target = physTarget

                    # mark target as not ready
                    this.readyTable.clear(physTarget)
                else:
                    # free list empty, cannot do this yet, break
                    this.renameQueue.pushBack(instr)
                    break

            this.debug("Renamed Instruction")

            instr.renamed = True
            instr.renameCycle = this.cycle
            instr.dependencies = physDependencies
            this.dispatchQueue.push(instr)

            # signal progress
            this.progress()

    # dispatch renamed instructions to IQ, ROB, and LSQ (if necessary)
    def dispatch (this):
        while not this.dispatchQueue.isEmpty():
            this.debug("Dispatched instruction")

            instr = this.dispatchQueue.pull()
            instr.dispatchCycle = this.cycle
            # put in IQ and ROB
            this.issueQueue.append(instr)
            this.reorderBuffer.append(instr)

            # put in LSQ if it does memory (is load or store)
            if instr.doesMemory:
                this.lsq.append(instr)

            # signal progress
            this.progress()

    # see which instructions can issue
    # issue at most issueWidth instructions
    def issue (this):
        issued = 0
        for instr in list(this.issueQueue):
            if issued >= this.issueWidth:
                # maximum instruction issued, break
                break

            if this.isInstructionReady(instr):
                # instruction ready, issue
                this.debug("Issued instruction")

                instr.issueCycle = this.cycle
                this.issueQueue.remove(instr)

                if not instr.isLoadOrStore():
                    # only put non-LSQ entries in executing list
                    # LSQ need special handling
                    this.executing.append(instr)
                issued += 1

                # signal progress
                this.progress()

    # writeback executed instructions
    def writeback (this):

        # writeback regular instructions [R, I]
        for instr in this.executing:
            this.debug("Writeback instruction")

            # regular instruction does write-back after execution
            instr.writebackCycle = this.cycle

            # set target to ready (since issue is called next, can issue immediately)
            if instr.target:
                this.readyTable.ready(instr.target)

            # signal progress
            this.progress()

        # clear executing list for next frame
        this.executing = []

        # writeback issued memory instructions [L, S] (yes, stores writeback per the specification)
        for instr in this.lsq.getExecutable():
            if instr.hasIssued():
                this.debug("Writeback LS instruction")

                instr.writebackCycle = this.cycle
                this.lsq.remove(instr)
                if instr.target is not None:
                    this.readyTable.ready(instr.target)

                # signal progress
                this.progress()

    # commit completed instructions (at most issueWidth)
    def commit (this):
        committed = 0
        while (
            len(this.reorderBuffer) > 0
            and this.reorderBuffer[0].hasWroteback()
            and committed < this.issueWidth
        ):
            this.debug("Committed instruction")

            instr = this.reorderBuffer.pop(0)
            instr.commitCycle = this.cycle

            # free overwritten register
            if instr.overwritten is not None:
                this.freeingRegisters.append(instr.overwritten)

            # signal progress
            this.progress()

    # check if an instruction is ready (used in issue stage)
    def isInstructionReady (this, instr):
        # check if all the dependencies are ready
        if not all(this.readyTable.isReady(dep) for dep in instr.dependencies):
            return False

        # for load and store, check if conservative ordering allows issuance
        if instr.isLoadOrStore():
            return this.lsq.canExecute(instr)

        # normal instruction
        return True

    # advance the cycle
    def advanceCycle (this):
        # put freed registers back in free list
        for freeReg in this.freeingRegisters:
            this.freeList.free(freeReg)
        this.freeingRegisters = []

        # next cycle
        this.cycle += 1

        this.debug("Advanced cycle")

    # write to output file
    def writeOutput (this):
        if this.isScheduling():
            # quit because of lack of progress, write an empty file
            this.outFile.write("")
            this.outFile.close()
            return

        # for each instruction, write a list of it's stage completion cycles on a new line
        for instr in this.instructions:
            this.outFile.write("%s,%s,%s,%s,%s,%s,%s\n" % (
                instr.fetchCycle,
                instr.decodeCycle,
                instr.renameCycle,
                instr.dispatchCycle,
                instr.issueCycle,
                instr.writebackCycle,
                instr.commitCycle,
            ))

        # close file
        this.outFile.close()

    def debug (this, msg):
        if this.isDebug:
            print(msg)

    def __repr__ (this):
        return "[OutputOfOrderScheduler cycle=%d]" % (this.cycle)
        

# handle command line and start program
def main (args):
    # handle command line args
    if len(args) != 2:
        print("Usage: python main.py [input file]")
        sys.exit(1)
    (_, fileName) = args

    # create and run scheduler
    ooo = OutOfOrderScheduler(fileName)
    ooo.schedule()

    # write out results
    ooo.writeOutput()


# call main if this is the main file
if __name__ == "__main__":
    main(sys.argv)
