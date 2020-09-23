#!/usr/bin/python
# vim: set et ts=4 sw=4 :
# -*- coding: cp437-*-

import sys
import curses
from curses.textpad import Textbox, rectangle
import time
import calendar
import string
import struct
from datetime import datetime
from functools import partial, wraps

# Discussion of handling mouse escape sequences can be found at:
#   http://manpages.ubuntu.com/manpages/xenial/man4/console_codes.4.html
#   ftp://xcb.freedesktop.org/pub/X11R6.7.0/PDF/ctlseqs.pdf
#   https://invisible-island.net/xterm/ctlseqs/ctlseqs.html#h2-Mouse-Tracking

epoch = datetime(1970, 1, 1)

def rawLog(strVal):
    return
    with open('hexEditor.py.log', 'a') as f:
        f.write(strVal)

# This is the version where we output byte at a time
byteDisplayFormatMap = {
        # Value is a 4-tuple: number of column sections, number of bytes in a
        # section, number of characters to display a byte, and formatStr
        'hex': (2, 8, 2, "{:02x}"),
        'decimal': (2, 5, 3, "{:03d}"),
        'octal': (3, 4, 3, "{:03o}"),
        'binary': (4, 1, 8, "{:08b}"),
}
validInputChars = {
        'hex': '01234567890abcdefABCDEF',
        'decimal': '0123456789',
        'octal': '01234567',
        'binary': '01',
}
numberBases = {
        'hex': 16,
        'decimal': 10,
        'octal': 8,
        'binary': 2,
}

"""
>>> "{:08b}".format(35)
'00100011'
>>> "{:03o}".format(35)
'043'
>>> "{:03d}".format(35)
'035'
>>> "{:02x}".format(35)
'23'
>>>

"""


def isInRectangle(point, ulPoint, lrPoint):
    y, x = point
    uly, ulx = ulPoint
    lry, lrx = lrPoint
    return uly <= y <= lry and ulx <= x <= lrx

class DataField(object):
    max_size = 0

    def __init__(self, hex_editor):
        self._hex_editor = hex_editor

    @property
    def strVal(self):
        return self._strVal

    @strVal.setter
    def strVal(self, val):
        raise NotImplementedError("Must be overridden")

    def output(self, win, y, x, colornum):
        outStr = "%s: %s" % (self.header, self._strVal)
        win.addstr(y, x, outStr, curses.color_pair(colornum))
        self.displayWidth = len(outStr)
        self.y = y
        self.x = x

    def containsPoint(self, y, x):
        return isInRectangle((y, x), (self.y, self.x), (self.y, self.x+self.displayWidth-1))

class IntField(DataField):
    def __init__(self, hex_editor):
        DataField.__init__(self, hex_editor)
        endian = ">" if self._hex_editor.endian == "big" else "<"
        self.cursorPos = self._hex_editor._cursorPos
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes):
            byteStr = self._hex_editor._data_bytes[self.cursorPos:self.cursorPos+self.byte_count]
            (intVal,) = struct.unpack(endian+self.recFmt, byteStr)
            self._strVal = "%d" % intVal
        else:
            self._strVal = None

    @property
    def strVal(self):
        return self._strVal

    @strVal.setter
    def strVal(self, val):
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes):
            self._strVal = val
            endian = ">" if self._hex_editor.endian == "big" else "<"
            bytesStr = struct.pack(endian+self.recFmt, int(val))
            self._hex_editor._data_bytes = (
                    self._hex_editor._data_bytes[:self.cursorPos] + 
                    bytesStr + 
                    self._hex_editor._data_bytes[self.cursorPos+len(bytesStr):]
                    )
        else:
            self._strVal = None

class S8Field(IntField):
    recFmt = 'b'
    header = 'S8'
    byte_count = 1
    max_size = 4

class U8Field(IntField):
    recFmt = 'B'
    header = 'U8'
    byte_count = 1
    max_size = 3

class S16Field(IntField):
    recFmt = 'h'
    header = 'S16'
    byte_count = 2
    max_size = 6

class U16Field(IntField):
    recFmt = 'H'
    header = 'U16'
    byte_count = 2
    max_size = 5

class S32Field(IntField):
    recFmt = 'i'
    header = 'S32'
    byte_count = 4
    max_size = 11

class U32Field(IntField):
    recFmt = 'I'
    header = 'U32'
    byte_count = 4
    max_size = 10

class TimestampField(DataField):
    byte_count = 4
    recFmt = 'i'
    max_size = 19
    timeFmt = '%Y/%m/%d %H:%M:%S'

    def __init__(self, hex_editor):
        DataField.__init__(self, hex_editor)
        endian = ">" if self._hex_editor.endian == "big" else "<"
        self.cursorPos = self._hex_editor._cursorPos
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes):
            byteStr = self._hex_editor._data_bytes[self.cursorPos:self.cursorPos+self.byte_count]
            (intVal,) = struct.unpack(endian+self.recFmt, byteStr)
            self._strVal = time.strftime(self.timeFmt, self.timeFunc(intVal))
        else:
            self._strVal = None

    @property
    def strVal(self):
        return self._strVal

    @strVal.setter
    def strVal(self, val):
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes):
            try:
                ts = time.strptime(val, self.timeFmt)
            except Exception as e:
                # Would be better to give feedback here...
                self._hex_editor.auxData.append(str(e))
                return
            intVal = self.inverseTimeFunc(ts)
            endian = ">" if self._hex_editor.endian == "big" else "<"
            bytesStr = struct.pack(endian+self.recFmt, intVal)
            self._hex_editor._data_bytes = (
                    self._hex_editor._data_bytes[:self.cursorPos] + 
                    bytesStr + 
                    self._hex_editor._data_bytes[self.cursorPos+len(bytesStr):]
                    )
        else:
            self._strVal = None

class UTCField(TimestampField):
    header = "UTC"
    timeFunc = time.gmtime
    def inverseTimeFunc(self, ts):
        return calendar.timegm(ts)

class CSTField(TimestampField):
    header = "CST"
    timeFunc = time.localtime
    def inverseTimeFunc(self, ts):
        return time.mktime(ts)

# ePriority Mailbag timestamp field
class MBTimestampField(DataField):
    byte_count = 8
    max_size = 19
    header = 'UTC'
    timeFmt = '%Y/%m/%d %H:%M:%S'

    def __init__(self, hex_editor):
        DataField.__init__(self, hex_editor)
        self.cursorPos = self._hex_editor._cursorPos
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes) and self._hex_editor._data_bytes:
            byteStr = self._hex_editor._data_bytes[self.cursorPos:self.cursorPos+self.byte_count]
            try:
                intVal = int(byteStr, 16)
            except ValueError:
                self._strVal = None
                return
            self._strVal = time.strftime(self.timeFmt, time.gmtime(intVal))
        else:
            self._strVal = None

    @property
    def strVal(self):
        return self._strVal

    @strVal.setter
    def strVal(self, val):
        if self.cursorPos + self.byte_count <= len(self._hex_editor._data_bytes):
            try:
                ts = time.strptime(val, self.timeFmt)
            except Exception as e:
                # Would be better to give feedback here...
                self._hex_editor.auxData.append(str(e))
                return
            intVal = calendar.timegm(ts)
            bytesStr = "%08x" % intVal
            self._hex_editor._data_bytes = (
                    self._hex_editor._data_bytes[:self.cursorPos] + 
                    bytesStr + 
                    self._hex_editor._data_bytes[self.cursorPos+len(bytesStr):]
                    )
        else:
            self._strVal = None

# Decorator function for display elements where the mousemask should be clear
# (ignore mouse events).
def nomouse(func):
    @wraps(func)
    def wrapper_nomouse(*args, **kwargs):
        avail_mask, saved_mask = curses.mousemask(0)
        try:
            return func(*args, **kwargs)
        finally:
            curses.mousemask(saved_mask)
    return wrapper_nomouse

class ExitProgram(Exception):
    pass

# I am going to assume we can hold the whole thing in memory at once. It would
# be more flexible for very large files to be able to seek through the file
# with just a small buffer, but that makes everything much more complicated
# when editing and maybe not saving.
class HexEditor(object):
    # For displaying data at the bottom of the screen
    complexDataClassRows = [
        [S8Field, S16Field, S32Field, UTCField],
        [U8Field, U16Field, U32Field, CSTField],
    ]
    complexDataInstanceRows = None

    @property
    def textFormat(self):
        return self._textFormat
    @textFormat.setter
    def textFormat(self, tf):
        if not tf in ('ascii', 'ebcdic'):
            raise TypeError("Invalid text format: %r" % tf)
        self._textFormat = tf

    @property
    def dataFormat(self):
        return self._dataFormat
    @dataFormat.setter
    def dataFormat(self, tf):
        if not tf in ('hex', 'octal', 'decimal', 'binary'):
            raise TypeError("Invalid data format: %r" % tf)
        self._dataFormat = tf

    @property
    def offsetFormat(self):
        return self._offsetFormat
    @offsetFormat.setter
    def offsetFormat(self, tf):
        if not tf in ('hex', 'decimal'):
            raise TypeError("Invalid offset format: %r" % tf)
        self._offsetFormat = tf

    @property
    def endian(self):
        return self._endian
    @endian.setter
    def endian(self, endianness):
        if not endianness in ('big', 'little'):
            raise TypeError("Invalid endian specification: %r" % endianness)
        self._endian = endianness

    @property
    def mailbag(self):
        return self._mailbag
    @mailbag.setter
    def mailbag(self, mb):
        self._mailbag = bool(mb)
        if mb:
            self.complexDataClassRows = [
                [S8Field, S16Field, S32Field, MBTimestampField],
                [U8Field, U16Field, U32Field, ],
            ]
        else:
            self.complexDataClassRows = [
                [S8Field, S16Field, S32Field, UTCField],
                [U8Field, U16Field, U32Field, CSTField],
            ]
        complexDataInstanceRows = None

    @property
    def debug(self):
        return self._debug
    @debug.setter
    def debug(self, debug):
        self._debug = bool(debug)

    @property
    def recSize(self):
        return self._recSize
    @recSize.setter
    def recSize(self, recSize):
        if recSize is not None and (not isinstance(recSize, int) or recSize <= 0):
            raise ValueError("Invalid record size: %r" % (recSize,))
        self._recSize = recSize

    def __init__(self, filename, isWritable=False):
        self._stdscr = None
        self._filename = filename
        #if isWritable:
        #    #self._fileobj = open(filename, 'rb+')
        #    self._fileobj = open(filename, 'rb')
        #else:
        #    self._fileobj = open(filename, 'rb')
        # For now, read only and read the whole buffer at once.
        with open(filename, 'rb') as f:
            self._data_bytes = f.read()

    def computeScreenParams(self, stdscr):
        # Compute all the positions of everything based on the screen size
        self.screenRows, self.screenCols = stdscr.getmaxyx()
        self.offsetWidth = 8
        (self.dataSectionCount, self.dataSectionBytes, self.dataColByteCount,
                self.dataDisplayFormat) = byteDisplayFormatMap[self.dataFormat]
        if self.recSize:
            # For fixed record size, rowByteCount would get dynamically computed.
            # TODO iff we are running with fixed record width, compute the number
            # of full column sections of data and text that can be displayed with
            # the current screen width (should be a basic algebra equation that can
            # be solved). Base all the numbers below on that. Also correspondingly
            # track the number of bytes that can be displayed on screen. The outer
            # code will need to know this to decide of horizontal scrolling is
            # needed to get the current cursor pos on screen.
            self.rowByteCount = self.recSize
            self.visibleDataSectionCount = int(
                    (self.screenCols - 8) /
                    (self.dataSectionBytes * self.dataColByteCount + self.dataSectionBytes + 2)
            )
            self.dataSectionCount, self.partialSection = divmod(self.rowByteCount, self.dataSectionBytes)
        else:
            self.rowByteCount = self.dataSectionCount * self.dataSectionBytes
            self.visibleDataSectionCount = self.dataSectionCount
            self.partialSection = 0

        self.dataSectionWidth = self.visibleDataSectionCount*self.dataSectionBytes*self.dataColByteCount + self.dataSectionCount - 1
        self.dataLeftCol = self.offsetWidth + 1
        self.dataRightCol = self.dataLeftCol + self.dataSectionWidth - 1
        self.dataFirstRow = 0
        self.statusRow = self.screenRows-1
        # compute last rows more dynamically, depending on how many translated values at the bottom
        self.dataLastRow = self.statusRow-len(self.complexDataInstanceRows)-2
        self.dataRowCount = self.dataLastRow + 1 - self.dataFirstRow

        self.textSectionWidth = self.visibleDataSectionCount*self.dataSectionBytes + self.dataSectionCount - 1
        self.textLeftCol = self.dataRightCol+2
        self.textRightCol = self.textLeftCol + self.textSectionWidth - 1

    def setDataFields(self):
        self.complexDataInstanceRows = []
        for complexDataClassRow in self.complexDataClassRows:
            complexInstanceRow = []
            for complexDataClass in complexDataClassRow:
                complexInstanceRow.append(complexDataClass(self))
            self.complexDataInstanceRows.append(complexInstanceRow)

    @property
    def textDisplayCursorPos(self):
        # TODO Rework for visibleDisplay and scrolling
        # Return the screen coordinates of self._cursorPos in the text
        # area. May be used when tabbing into the data display area to decide
        # where to put the cursor.
        cursorLine, rowBytePos = divmod(self._cursorPos, self.rowByteCount)
        lastDisplayLine = self._firstDisplayLine + self.dataRowCount - 1

        # Assume we must be on the visible screen. Presumably we would not use
        # this when cursorPos is off the screen.
        assert cursorLine >= self._firstDisplayLine, "Invalid cursorLine: %s" % cursorLine
        assert cursorLine <= lastDisplayLine, "Invalid cursorLine: %s" % cursorLine
        yPos = cursorLine - self._firstDisplayLine + self.dataFirstRow
        # To get the xPosition we need to add the single space between each section
        xPos = self.textLeftCol + rowBytePos + rowBytePos//self.dataSectionBytes
        return yPos, xPos

    @property
    def dataDisplayCursorPos(self):
        # TODO Rework for visibleDisplay and scrolling
        # Return the screen coordinates of self._cursorPos in the data
        # area. May be used when tabbing into the data display area to decide
        # where to put the cursor.
        cursorLine, rowBytePos = divmod(self._cursorPos, self.rowByteCount)
        lastDisplayLine = self._firstDisplayLine + self.dataRowCount - 1

        # Assume we must be on the visible screen. Presumably we would not use
        # this when cursorPos is off the screen.
        assert cursorLine >= self._firstDisplayLine, "Invalid cursorLine: %s" % cursorLine
        assert cursorLine <= lastDisplayLine, "Invalid cursorLine: %s" % cursorLine
        yPos = cursorLine - self._firstDisplayLine + self.dataFirstRow
        # To get the xPosition we need to add the single space between each section
        xPos = self.dataLeftCol + self.dataColByteCount*rowBytePos + rowBytePos//self.dataSectionBytes
        return yPos, xPos

    def convertScreenPosToCursorPos(self, y, x):
        # TODO Rework for visibleDisplay and scrolling
        # Convert screen coordinates to the absolute byte position within
        # the file. (for converting a mouse click to a cursor movement).
        # First, I guess we decide if it is in the text area or data area. Return None (or maybe the current pos) if outside both.
        if self.dataFirstRow <= y <= self.dataLastRow:
            yComponent = self.rowByteCount*(y-self.dataFirstRow+self._firstDisplayLine)
        else:
            return None
        if self.dataLeftCol <= x <= self.dataRightCol:
            # Data area
            displayColsPerByte = self.dataColByteCount
            columnPtr = self.dataLeftCol
        elif self.textLeftCol <= x <= self.textRightCol:
            # Text area
            displayColsPerByte = 1
            columnPtr = self.textLeftCol
        else:
            return None
        # Inefficient, but we will count our way up until we find our position.
        # This inner function lets us more easily skip out of the nested for
        # loops when we find our answer.
        def findByteOffset(columnPtr):
            byteOffsetPtr = 0
            for dataSection in range(self.dataSectionCount):
                for sectionByteCounter in range(self.dataSectionBytes):
                    columnPtr += displayColsPerByte
                    if columnPtr > x:
                        return byteOffsetPtr
                    byteOffsetPtr += 1
                # Increment the columnPtr for the space between sections
                columnPtr += 1
            else:
                assert False, "Should never happen"
        return yComponent + findByteOffset(columnPtr)

    def resize(self, stdscr):
        # Compute the required width below instead of constant.
        self.computeScreenParams(stdscr)
        # TODO Rework for visibleDisplay and scrolling
        assert self.screenCols > self.textRightCol, "Need at least %d columns for %s data display (%d)" % (
                textRightCol+1, self.dataFormat, self.screenCols) 

        # TODO Insted of failing, set a tooNarrowMessage that redraw will
        # display until we resize the screen larger.
        if curses.is_term_resized(self.screenRows, self.screenCols):
            curses.resizeterm(self.screenRows, self.screenCols)


    def redraw(self, stdscr, normalize=False):
        #stdscr.clear()
        stdscr.erase()

        ####################################
        #
        # Offset, Data and Text areas
        #
        ####################################
        # normalize is when the data format (in particular) has changed. We
        # will shift the row containing the cursor to the first row.
        if normalize:
            # We must draw frames of size rowByteCount. Likely cursor is not on
            # an even boundary. We will make the first line contain cursor
            self._firstDisplayLine = self._cursorPos // self.rowByteCount
        firstRowBytePos = self._firstDisplayLine * self.rowByteCount
        displayRow = 0
        def addstr(row, col, strVal, colornum, addAttr=0):
            attr = curses.A_BOLD if colornum else 0
            stdscr.addstr(row, col, strVal, curses.color_pair(colornum) | attr | addAttr)
            rawLog('row: %r, col: %r, %r (%r)\n' % (row, col, strVal, curses.color_pair(colornum) | attr | addAttr))
        # TODO Rework for visibleDisplay and scrolling
        for rowPtr in range(firstRowBytePos, firstRowBytePos + self.rowByteCount*(self.dataLastRow+1), self.rowByteCount):
            # Get the row offset in the correct format (hex or decimal)
            if self._offsetFormat == 'hex':
                offsetStr = "%08x" % rowPtr
            else:
                offsetStr = "%08d" % rowPtr
            stdscr.addstr(displayRow, 0, offsetStr)

            displayCol = 9
            textDisplayCol = self.textLeftCol
            rowBytePtr = rowPtr
            for dataSection in range(self.dataSectionCount):
                color_num = 0
                for sectionByteCounter in range(self.dataSectionBytes):
                    if rowBytePtr == self._cursorPos:
                        extraAttr = curses.A_REVERSE | curses.A_BOLD
                        self._displayCursorRow = displayRow
                        self._displayDataCursorCol = displayCol
                        self._displayTextCursorCol = textDisplayCol
                    else:
                        extraAttr = 0
                    if rowBytePtr >= len(self._data_bytes):
                        addstr(displayRow, displayCol, "  ", 0)
                    else:
                        addstr(displayRow, displayCol,
                                self.dataDisplayFormat.format(ord(self._data_bytes[rowBytePtr])),
                                color_num, extraAttr)
                    try:
                        if rowBytePtr >= len(self._data_bytes):
                            addstr(displayRow, textDisplayCol, " ", 0)
                        else:
                            addstr(displayRow, textDisplayCol, self.makePrintable(self._data_bytes[rowBytePtr]),
                                    0, extraAttr)
                                    #color_num, extraAttr)
                    except curses.error as e:
                        # Stupid workaround, but this is a known issue in
                        # curses in general if you write to the lower right
                        # hand corner and the cursor moves beyond the bounds of
                        # the screen.  Does not always seem to be an issue.
                        # Everything still displays properly.
                        if str(e) == "addstr() returned ERR":
                            pass
                            rawLog("addstr() returned ERR")
                        else:
                            raise
                    color_num = 1 - color_num
                    displayCol += self.dataColByteCount
                    textDisplayCol += 1
                    rowBytePtr += 1
                displayCol += 1
                textDisplayCol += 1


            displayRow += 1

        
        ####################################
        #
        # Separator lines
        #
        ####################################
        # TODO When adding scrolling, if the left or right edge is off screen,
        # add a scrolling indicator (vertical line of alternating / and \ chars
        # instead of just a line of | characters).
        stdscr.vline(0, self.dataLeftCol-1, '|', self.dataLastRow+1-self.dataFirstRow)
        stdscr.vline(0, self.textLeftCol-1, '|', self.dataLastRow+1-self.dataFirstRow)
        stdscr.hline(self.dataLastRow+1, 0, '-', self.textRightCol)
        stdscr.addch(self.dataLastRow+1, self.dataLeftCol-1, '+')
        stdscr.addch(self.dataLastRow+1, self.textLeftCol-1, '+')

        ####################################
        #
        # Auxiliary data values
        #
        ####################################
        firstValueRow = self.statusRow - len(self.complexDataInstanceRows)
        for rowOffset, complexInstanceRow in enumerate(self.complexDataInstanceRows):
            colOffset = 0 
            for complexDataInstance in complexInstanceRow:
                complexDataInstance.output(stdscr, firstValueRow+rowOffset, colOffset, 0)
                colOffset += complexDataInstance.displayWidth + 2

        ####################################
        #
        # Status Bar
        #
        ####################################
        # Update the cursor location, etc.
        curStatusCol = 0
        if self._offsetFormat == 'hex':
            cursorPosStr = "Cursor: %08x" % self._cursorPos
        else:
            cursorPosStr = "Cursor: %08d" % self._cursorPos
        addstr(self.statusRow, curStatusCol, cursorPosStr, 1, 0)
        curStatusCol += len(cursorPosStr)+2

        modeStr = "Mode:%s" % self.dataFormat[:3].title()
        addstr(self.statusRow, curStatusCol, modeStr, 1, 0)
        curStatusCol += len(modeStr) + 2

        if self._editChars:
            # Show accumulated edit chars and update curStatusCol
            (colSections, bytesPerSection, charsPerByte, formatStr) = byteDisplayFormatMap[self.dataFormat]
            editCharStr = "[%*s]" % (charsPerByte, self._editChars)
            curStatusCol -= 1
            addstr(self.statusRow, curStatusCol, editCharStr, 2, 0)
            curStatusCol += len(editCharStr) + 2

        if self._modified:
            curStatusCol -= 1
            addstr(self.statusRow, curStatusCol, "MOD", 2, 0)
            curStatusCol += 3 + 2

        # Show which input area
        inputAreaStr = "in:%s" % self.inputArea
        addstr(self.statusRow, curStatusCol, inputAreaStr, 1, 0)
        curStatusCol += len(inputAreaStr) + 2

        sizeStr = "Size: %d" % len(self._data_bytes)
        addstr(self.statusRow, curStatusCol, sizeStr, 1, 0)
        curStatusCol += len(sizeStr) + 2

        if self.debug:
            for ypos, auxLine in enumerate(self.auxData, 6):
                stdscr.addstr(ypos, 75, auxLine)

        # Ultimately we need to know which input area our cursor is on the
        # screen. We are just assuming the data area for now.
        if self.inputArea == "data":
            stdscr.move(self._displayCursorRow, self._displayDataCursorCol)
        else:
            stdscr.move(self._displayCursorRow, self._displayTextCursorCol)
        try:
            curses.curs_set(2)
        except curses.error:
            # If terminfo does not support changing cursor visibility, we
            # should keep going anyway
            pass
        stdscr.refresh()

    def readEscapes(self, win):
        # We have already read an escape character. We are going to do a
        # non-blocking read (in case it was just an escape char typed). We will
        # consume chars until we get all of them, then translate the escape
        # sequemce and return the char name.
        win.timeout(0)
        try:
            escapeSequence = []
            while True:
                ch = win.getch()
                if ch == -1:
                    break
                if ch >= 256:
                    return ch, curses.keyname(ch)
                escapeSequence.append(ch)
        finally:
            win.timeout(-1)
        escape = "".join([chr(ch) for ch in escapeSequence])
        # Now translate the escape sequence and return the keyname
        known_escapes = {
            "[11~": "KEY_F(1)",
            "[12~": "KEY_F(2)",
            "[13~": "KEY_F(3)",
            "[14~": "KEY_F(4)",
            "[15~": "KEY_F(5)",
            "[17~": "KEY_F(6)",
            "[18~": "KEY_F(7)",
            "[19~": "KEY_F(8)",
            "[20~": "KEY_F(9)",
            "[21~": "KEY_F(10)",
            "[23~": "KEY_F(11)",
            "[24~": "KEY_F(12)",
            "[1~": "KEY_HOME",
            "[4~": "KEY_END",
            "[5~": "KEY_PPAGE",
            "[6~": "KEY_NPAGE",
            "": "^[",
        }
        key = known_escapes.get(escape, "")
        return "\x1b" + escape, key

    def moveCursor(self, byteCount, normalize=False):
        # TODO Consider whether we need to take into account fixed width rows
        # when doing this. Especially when determining whether horizontal
        # scrolling is indicated as a result of the movement.
        #   * If fixed width, we should have an indicator of the leftmost
        #     visible column and the rightmost visible column. And, the current
        #     row number and the current column number. If we move outside of
        #     the visible columns, we must scoll horizontally to keep up.
        self._cursorPos += byteCount
        if byteCount >= 0:
            self._cursorPos = min(len(self._data_bytes)-1, self._cursorPos)
        if byteCount <= 0:
            self._cursorPos = max(0, self._cursorPos)
        cursorLine = self._cursorPos // self.rowByteCount
        eofFirstDisplayLine = max(len(self._data_bytes)//self.rowByteCount - self.dataRowCount + 1, 0)
        lastDisplayLine = self._firstDisplayLine + self.dataRowCount - 1

        if cursorLine < self._firstDisplayLine:
            self._firstDisplayLine = cursorLine
        elif cursorLine > lastDisplayLine:
            if normalize:
                self._firstDisplayLine = cursorLine
            else:
                self._firstDisplayLine += cursorLine-lastDisplayLine

        self._firstDisplayLine = max(self._firstDisplayLine, 0)
        self._firstDisplayLine = min(self._firstDisplayLine, eofFirstDisplayLine)

    def performMouseClick(self, y, x, stdscr):
        # Only called from within mainLoop. Multiple possible ways to detect a
        # mouse click, so we refactor the action to here to avoid repeated
        # complex code.
        if isInRectangle((y, x), (self.dataFirstRow, self.dataLeftCol), (self.dataLastRow, self.dataRightCol)):
            self.inputArea = "data"
            self._cursorPos = self.convertScreenPosToCursorPos(y, x)
        elif isInRectangle((y, x), (self.dataFirstRow, self.textLeftCol), (self.dataLastRow, self.textRightCol)):
            self.inputArea = "text"
            self._cursorPos = self.convertScreenPosToCursorPos(y, x)
        else:
            # One more chance. Walk through the data values to see if one of
            # them was clicked
            for complexInstanceRow in self.complexDataInstanceRows:
                for complexDataInstance in complexInstanceRow:
                    if complexDataInstance.containsPoint(y, x):
                        # Do the editing and exit
                        self.auxData.append(complexDataInstance.header+" clicked")
                        # Open an edit window with the complexDataInstance passed in.
                        self.showEditDialog(stdscr, complexDataInstance)
                        return

    def mainLoop(self, stdscr):
        curses.init_pair(1, curses.COLOR_BLUE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.mousemask(curses.BUTTON1_CLICKED)
        # We inconsistently see mouse events get sent, even when we set
        # mousemask, so we will also manually send an X11 escape sequence as
        # well. Not completely sure what we will see in this case, but if it
        # comes through as a curses KEY_MOUSE character, we will respond to
        # that. Otherwise we will try to capture and decode the raw escape
        # sequences.
        sys.stdout.write("\x1b[?1000h")
        sys.stdout.flush()
        curses.cbreak()
        self._editChars = ""
        self._modified = False
        self.inputArea = "data"
        curRawMouseState = None
        # Temporary for debugging
        self.auxData = []
        try:
            curses.curs_set(0)
        except curses.error:
            # If terminfo does not support changing cursor visibility, we
            # should keep going anyway
            pass
        stdscr.clear()
        self._cursorPos = 0
        self._firstDisplayLine = 0
        loopCount = 0
        while True:
            # This might be way overkill, but in many cases we might not be
            # able to detect that a resize has occurred. It might just make
            # sense to check every time through and react. Running resize
            # before redrawing the screen lets us react properly if someone
            # resized while a dialog was open.
            self.setDataFields()
            self.resize(stdscr)
            self.redraw(stdscr)
            ch = stdscr.getch()

            if ch == 27:
                ch, key = self.readEscapes(stdscr)
            elif ch > -1:
                key = curses.keyname(ch)

            if ch == -1:
                stdscr.timeout(-1)
                stdscr.clearok(True)
                continue
            else:
                stdscr.timeout(500)

            self.auxData.append("%d: %r ==> %s" % (loopCount, ch, key))

            if self.inputArea == "data" and key and key in '0123456789abcdefABCDEF':
                # Here, we know it is not one of the navigation or control
                # chars. We are editing binary data directly. Skip everything
                # else.
                # Track of modified
                # Accumulate chars (if appropriate for the mode we are in).
                (colSections, bytesPerSection, charsPerByte, formatStr) = byteDisplayFormatMap[self.dataFormat]
                if key in validInputChars[self.dataFormat]:
                    self._editChars += key
                    if len(self._editChars) == charsPerByte:
                        updateByte = int(self._editChars, numberBases[self.dataFormat])
                        if updateByte < 256:
                            # Messy here. Would be neater in Python3 with a byte array, I think.
                            self._data_bytes = self._data_bytes[:self._cursorPos] + chr(updateByte) + self._data_bytes[self._cursorPos+1:]
                            self._modified = True
                            self.moveCursor(1)
                        # Reset, whether or not the input was valid.
                        self._editChars = ""
            elif self.inputArea == "text" and 32 <= ch <= 127:
                try:
                    encodedByte = chr(ch).encode('cp1252' if self.textFormat == 'ascii' else 'cp1140')
                    self._data_bytes = self._data_bytes[:self._cursorPos] + encodedByte + self._data_bytes[self._cursorPos+1:]
                    self._modified = True
                    self.moveCursor(1)
                except UnicodeError:
                    # No edit if illegal char
                    pass
            else:
                self._editChars = ""
                if ch == curses.KEY_RESIZE:
                    self.resize(stdscr)
                elif ch == curses.KEY_NPAGE or key == 'KEY_NPAGE':
                    # Compute the next page down and set the positions properly and redraw
                    self._firstDisplayLine += self.dataRowCount
                    self.moveCursor(self.rowByteCount * self.dataRowCount)
                elif ch == curses.KEY_PPAGE or key == 'KEY_PPAGE':
                    # Compute the previous page up and set the positions properly and redraw
                    self._firstDisplayLine -= self.dataRowCount
                    self.moveCursor(-self.rowByteCount * self.dataRowCount)
                elif ch == curses.KEY_DOWN:
                    self.moveCursor(self.rowByteCount)
                elif ch == curses.KEY_UP:
                    self.moveCursor(-self.rowByteCount)
                elif ch == curses.KEY_RIGHT:
                    self.moveCursor(1)
                elif ch == curses.KEY_LEFT:
                    self.moveCursor(-1)
                elif ch == curses.KEY_SRIGHT:
                    # TODO Scroll right
                    pass
                elif ch == curses.KEY_SLEFT:
                    # TODO Scroll left
                    pass
                elif key == "KEY_HOME":
                    self._cursorPos = 0
                    #self._firstDisplayLine = 0
                    self.moveCursor(0)
                elif key == "KEY_END":
                    self._cursorPos = len(self._data_bytes)-1
                    self.moveCursor(0)
                elif key == "^I":
                    # Change the input area to the next one
                    self.inputArea = "data" if self.inputArea == "text" else "text"
                elif ch == curses.KEY_BTAB:
                    # Change the input area to the previous one
                    self.inputArea = "data" if self.inputArea == "text" else "text"
                elif key == "^G":
                    # Goto offset. + or - at beginning means relative. Open new
                    # Window to prompt.
                    self.showNavigateToOffset(stdscr)
                    self.moveCursor(0, normalize=True)
                elif key == "^F":
                    # Find (Search)
                    location = self.showSearchDialog(stdscr)
                    if location is not None:
                        self._cursorPos = location
                        self.moveCursor(0)
                elif key == "KEY_F(1)":
                    self.showHelp(stdscr)
                elif self.debug and (key == "KEY_F(11)"):
                    self.showDialog(stdscr, [
                        "curses.has_colors() ==> %r" % curses.has_colors(),
                        "curses.can_change_color() ==> %r" % curses.can_change_color(),
                        "curses.COLORS ==> %r" % curses.COLORS,
                    ])
                elif key == "KEY_F(10)":
                    self.showMainMenu(stdscr)
                    # Recompute, because a change in formats changes the screen layout.
                    self.computeScreenParams(stdscr)
                    # And, just in case the format change shifted the cursor
                    # off screen, do a dummy null move, which will scroll, only
                    # if necessary, to get back on screen.
                    self.moveCursor(0)
                elif key == "^W" and self._modified:
                    # Write the file back out. There are no safety rails here.
                    # If you say write it and you have permission, it does it.
                    self.saveFile()
                elif key == "KEY_MOUSE":
                    # With the touch pad, I never see BUTTON1_CLICKED, I see BUTTON1_PRESSED followed by BUTTON1_RELEASED
                    idVal, x, y, z, bstate = curses.getmouse()
                    if bstate and (curses.BUTTON1_CLICKED or curses.BUTTON1_RELEASED):
                        # Mouse button was clicked.
                        # Find where we clicked and perform appropriate action
                        self.performMouseClick(y, x, stdscr)
                elif isinstance(ch, str) and ch.startswith("\x1b[M") and len(ch) == 6:
                    if ord(ch[-3]) & 3 == 0:
                        curRawMouseState = curses.BUTTON1_PRESSED
                    elif curRawMouseState == curses.BUTTON1_PRESSED and ord(ch[-3]) & 3 == 3:
                        curRawMouseState = None
                        # Now we have a mouse up after button was pressed (or
                        #   curses.BUTTON1_RELEASED)
                        xCode, yCode = tuple(ch[-2:])
                        x = ord(xCode) - 33
                        y = ord(yCode) - 33
                        # Mouse button was clicked.
                        # Find where we clicked (Repeated from above)
                        self.performMouseClick(y, x, stdscr)

            loopCount += 1
            if key == "KEY_MOUSE" and self.debug:
                buttonList = []
                for i in range(1,5):
                    for state in ("PRESSED", "RELEASED", "CLICKED", "DOUBLE_CLICKED", "TRIPLE_CLICKED",):
                        stateName = "BUTTON%d_%s" % (i, state)
                        if bstate & getattr(curses, stateName):
                            buttonList.append(stateName)
                for shiftState in ("SHIFT", "CTRL", "ALT"):
                    stateName = "BUTTON_%s" % shiftState
                    if bstate & getattr(curses, stateName):
                        buttonList.append(stateName)
                stateStr = ' | '.join(buttonList)
                self.auxData.append("  Mouse: (%d, %d) %d [%s]" % (x, y, bstate, stateStr))
            del self.auxData[0:-15]

    def makePrintable(self, strVal):
        #return "".join([ch if ch in string.printable else "?" for ch in strVal])
        if self.textFormat == 'ebcdic':
            try:
                strVal = strVal.decode('cp1140').encode('cp1252')
            except UnicodeError:
                strVal = '.'
        #return strVal if strVal >= " " else "."
        return "".join([ch if ch in string.printable  and ch >= " " else "." for ch in strVal])

    @nomouse
    def showDialog(self, stdscr, lineList, rowCount=20, colCount=50, startRow=2, startCol=5):
        # Make a new window
        win = stdscr.subwin(rowCount, colCount, startRow, startCol)
        win.erase()
        win.bkgdset(' ')
        win.border('|', '|', '-', '-', '+', '+', '+', '+')
        for lineNum, line in enumerate(lineList, 1):
            win.addstr(lineNum, 1, line)
        win.refresh()
        ch = win.getch()

    def rectangle(self, win, uly, ulx, lry, lrx):
        win.vline(uly+1, ulx, '|', lry-uly-1)
        win.vline(uly+1, lrx, '|', lry-uly-1)
        win.hline(uly, ulx+1, '-', lrx-ulx-1)
        win.hline(lry, ulx+1, '-', lrx-ulx-1)
        win.addch(uly, ulx, '+')
        win.addch(uly, lrx, '+')
        win.addch(lry, ulx, '+')
        win.addch(lry, lrx, '+')

    @nomouse
    def showNavigateToOffset(self, stdscr):
        # Make a new window
        navScreen = stdscr.subwin(9, 33, 2, 5)
        navScreen.erase()
        navScreen.bkgdset(' ')
        navScreen.border('|', '|', '-', '-', '+', '+', '+', '+')
        navScreen.addstr(1, 1, "Enter offset to navigate")
        navScreen.addstr(2, 1, "  + or - for relative movement")
        navScreen.addstr(3, 1, "  Enter to submit")
        navScreen.addstr(4, 1, "  Submit empty box to Cancel")
        # Cannot seem to get usable ACS_ characters, so manually draw rectangle
        self.rectangle(navScreen, 5, 4, 5+1+1, 4+10+1)
        editWin = navScreen.subwin(1, 10, 2+6, 5+5)
        navScreen.refresh()
        box = Textbox(editWin)
        box.edit()
        # I think it automatically strips spaces, but just in case...
        results = box.gather().strip()
        if not results:
            return
        if results[0] in "+-":
            relativeDirection = 1 if results[0] == "+" else -1
            results = results[1:]
        else:
            relativeDirection = 0
        try:
            if relativeDirection or self.offsetFormat == "decimal":
                # XXX Maybe not the correct choice, but we always treat
                # relative movement as decimal.
                offset = int(results)
            else:
                # If we navigate to absolute address and we are displaying
                # addresses in hex, we should treat absolute position as hex.
                offset = int(results, 16)
        except ValueError:
            # Bad offset. No movement.
            return
        if relativeDirection:
            if relativeDirection > 0:
                self._cursorPos = min(len(self._data_bytes)-1, self._cursorPos + offset)
            else:
                self._cursorPos = max(0, self._cursorPos - offset)
        else:
            self._cursorPos = min(len(self._data_bytes)-1, offset)

    @nomouse
    def showEditDialog(self, stdscr, complexDataInstance):
        #
        editScreen = stdscr.subwin(12, 55, 0, 0)
        editScreen.erase()
        editScreen.bkgdset(' ')
        editScreen.border('|', '|', '-', '-', '+', '+', '+', '+')
        editScreen.addstr(1, 1, "Edit pattern hint")

        self.rectangle(editScreen, 5, 5, 5+1+1, 5+complexDataInstance.max_size+2)
        editWin = editScreen.subwin(1, complexDataInstance.max_size+1, 5+1, 5+1)
        editScreen.refresh()
        box = Textbox(editWin)
        editWin.addstr(0, 0, complexDataInstance.strVal if complexDataInstance.strVal else "")
        box.edit()
        # I think it automatically strips spaces, but just in case...
        results = box.gather().strip()
        if results != complexDataInstance.strVal:
            complexDataInstance.strVal = results
            self._modified = True

    # May eventually want to use mouse selection here to select search options.
    def showSearchDialog(self, stdscr):
        # For convenience, make search parameters persistent.
        if not hasattr(self, 'searchStr'):
            # Initialize all from defaults
            self.searchStr = ""
            self.searchDirection = "forward"
            self.searchFormat = "text"

        # Define a quick namespace object the we will use for elements to set
        # in redraw that we will use for mouse selection
        class Namespace(object): pass
        ns = Namespace()

        # Define the sub window and draw out the input search elements and the input box
        # Respond to Ctrl chars (or mouse events?) to change search parameters.
        # Perhaps even require a Ctrl char to open edit win to update search term
        # Enter key to run the search
        searchScreen = stdscr.subwin(12, 55, 0, 0)
        def redraw():
            searchScreen.erase()
            searchScreen.bkgdset(' ')
            searchScreen.border('|', '|', '-', '-', '+', '+', '+', '+')
            ns.textStr = "^Text: %s" % self.searchStr[:45]
            searchScreen.addstr(1, 1, ns.textStr)
            def dirSelected(direction):
                return "*" if self.searchDirection == direction else " "
            ns.directionHeader = "  ^Direction:"
            ns.forwardSelector = "[%s] Forward" % dirSelected("forward")
            ns.backwardSelector = "[%s] Backward" % dirSelected("backward")
            searchScreen.addstr(3, 1, ns.directionHeader + " " + ns.forwardSelector + "  " + ns.backwardSelector)
            searchScreen.addstr(5, 1, "  ^Format")
            def fmtSelected(fmt):
                return "*" if self.searchFormat == fmt else " "
            searchScreen.addstr(6, 1, "    [%s] S8   [%s] S16   [%s] S32   [%s] Data" % (
                fmtSelected("S8"), fmtSelected("S16"), fmtSelected("S32"), fmtSelected("data")))
            searchScreen.addstr(7, 1, "    [%s] U8   [%s] U16   [%s] U32   [%s] Text" % (
                fmtSelected("U8"), fmtSelected("U16"), fmtSelected("U32"), fmtSelected("text")))
            searchScreen.refresh()

        def performMouseClick(y, x, searchScreen):
            if y == 3:
                # Possible search direction change
                if 0 <= x - (1+len(ns.directionHeader)+1) <= len(ns.forwardSelector)-1:
                    self.searchDirection = "forward"
                elif 0 <= x - (1+len(ns.directionHeader)+1+len(ns.forwardSelector)+2) <= len(ns.backwardSelector)-1:
                    self.searchDirection = "backward"
            elif y == 6:
                if 5 <= x <= 10:
                    self.searchFormat = 'S8'
                elif 14 <= x <= 20:
                    self.searchFormat = 'S16'
                elif 24 <= x <= 30:
                    self.searchFormat = 'S32'
                elif 34 <= x <= 41:
                    self.searchFormat = 'data'
            elif y == 7:
                if 5 <= x <= 10:
                    self.searchFormat = 'U8'
                elif 14 <= x <= 20:
                    self.searchFormat = 'U16'
                elif 24 <= x <= 30:
                    self.searchFormat = 'U32'
                elif 34 <= x <= 41:
                    self.searchFormat = 'text'
            elif y == 1:
                if 1 <= x <= 1+len(ns.textStr)-1:
                    openEditWindow()

        def openEditWindow():
            # Open the editwin to edit the search text
            self.rectangle(searchScreen, 0, 7, 0+1+1, 7+45+1)
            editWin = searchScreen.subwin(1, 45, 1, 7+1)
            searchScreen.refresh()
            box = Textbox(editWin)
            box.edit()
            # I think it automatically strips spaces, but just in case...
            results = box.gather().strip()
            self.searchStr = results[:45]

        # Now run a main loop for character input here. Also allow a sub edit window overlaying the searchStr for ^T input.
        curRawMouseState = None
        searchScreen.timeout(-1)
        while True:
            redraw()
            ch = searchScreen.getch()

            if ch == 27:
                ch, key = self.readEscapes(searchScreen)
            else:
                key = curses.keyname(ch)

            self.auxData.append("   %r ==> %s" % ( ch, key))
            if key == "^T":
                openEditWindow()
            elif key == "^D":
                # Toggle the search direction
                self.searchDirection = "backward" if self.searchDirection == "forward" else "forward"
            elif key == "^F":
                # Toggle through the search format options
                self.searchFormat = {'S8': 'S16', 'S16': 'S32', 'S32': 'data',
                        'data': 'U8', 'U8': 'U16', 'U16': 'U32', 'U32': 'text',
                        'text': 'S8'}[self.searchFormat]
            elif key == "KEY_MOUSE":
                # With the touch pad, I never see BUTTON1_CLICKED, I see BUTTON1_PRESSED followed by BUTTON1_RELEASED
                idVal, x, y, z, bstate = curses.getmouse()
                if bstate and (curses.BUTTON1_CLICKED or curses.BUTTON1_RELEASED):
                    self.auxData.append("   Mouse ==> (%d, %d)" % ( y, x))
                    # Mouse button was clicked.
                    # Find where we clicked and perform appropriate action
                    performMouseClick(y, x, searchScreen)
            elif isinstance(ch, str) and ch.startswith("\x1b[M") and len(ch) == 6:
                if ord(ch[-3]) & 3 == 0:
                    curRawMouseState = curses.BUTTON1_PRESSED
                elif curRawMouseState == curses.BUTTON1_PRESSED and ord(ch[-3]) & 3 == 3:
                    curRawMouseState = None
                    # Now we have a mouse up after button was pressed (or
                    #   curses.BUTTON1_RELEASED)
                    xCode, yCode = tuple(ch[-2:])
                    x = ord(xCode) - 33
                    y = ord(yCode) - 33
                    self.auxData.append("   Mouse ==> (%d, %d)" % ( y, x))
                    # Mouse button was clicked.
                    # Find where we clicked (Repeated from above)
                    performMouseClick(y, x, searchScreen)
            elif isinstance(ch, str) and ch.startswith("\x1b[<0;"):
                # This is a third "uncooked" mouse sequence variation I have seen.
                # '\x1b[<0;1;2M'
                # '\x1b[<0;1;2m'
                if ch[-1] == "M":
                    curRawMouseState = curses.BUTTON1_PRESSED
                elif curRawMouseState == curses.BUTTON1_PRESSED and ch[-1] == "m":
                    curRawMouseState = None
                    # Now we have a mouse up after button was pressed (or
                    #   curses.BUTTON1_RELEASED)
                    _, xStr, yStr = ch[:-1].split(';')
                    # Ultimately, should make this computed relative to the
                    # origin of the subwin. Should probably make my own window
                    # subclass that can handle some of this specialized stuff
                    # for me.
                    x = int(xStr) - 1
                    y = int(yStr) - 1
                    self.auxData.append("   Mouse ==> (%d, %d)" % ( y, x))
                    # Mouse button was clicked.
                    # Find where we clicked (Repeated from above)
                    performMouseClick(y, x, searchScreen)
            elif key == "^J":
                # Do the search and return the found location (if any)
                # Step 1: convert the appropriate search input into a string of bytes.
                # Step 2: Then look for that string of bytes within self._data_bytes
                if self.searchFormat == "text":
                    if self.textFormat == 'ebcdic':
                        try:
                            bytesStr = self.searchStr.encode('cp1140')
                        except:
                            continue
                    else:
                        bytesStr = self.searchStr
                elif self.searchFormat == "data":
                    # Based on the display format, treat the sequence of digits as a sequence of bytes.
                    # XXX For our purposes, I assume a complete sequence of bytes. If any are illegal, just silently wait (continue)
                    # binary must be blocks of 8, octal and decimal, blocks of 3 and hex, blocks of 2.
                    workingStr = self.searchStr.replace(' ', '')
                    byteCount, remainder = divmod(len(workingStr), self.dataColByteCount)
                    if remainder:
                        # Needs to be an even number of bytes
                        continue
                    bytesStr = ""
                    base = numberBases[self.dataFormat]
                    try:
                        for ptr in range(0, len(workingStr), self.dataColByteCount):
                            bytesStr += chr(int(workingStr[ptr:ptr+self.dataColByteCount], base))
                    except ValueError as e:
                        self.auxData.append(str(e))
                        continue
                else:
                    endian = ">" if self.endian == "big" else "<"
                    if self.searchFormat == "S8":
                        packFmt = endian+'b'
                    elif self.searchFormat == "U8":
                        packFmt = endian+'B'
                    elif self.searchFormat == "S16":
                        packFmt = endian+'h'
                    elif self.searchFormat == "U16":
                        packFmt = endian+'H'
                    elif self.searchFormat == "S32":
                        packFmt = endian+'i'
                    elif self.searchFormat == "U32":
                        packFmt = endian+'I'
                    else:
                        # Don't think this can happen, but is here as a double check.
                        continue
                    try:
                        bytesStr = struct.pack(packFmt, int(self.searchStr))
                    except:
                        # Some kind of bad thing, either num too big or bad numeric
                        continue
                # Now search for the byte Str
                if self.searchDirection == "forward":
                    index = self._data_bytes.find(bytesStr, self._cursorPos+1)
                else:
                    index = self._data_bytes.rfind(bytesStr, 0, self._cursorPos+len(bytesStr)-1)
                if index > -1:
                    return index
            elif key == "^[":
                # Cancel without any navigation
                return None

    def showFileMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Save", "sS", self.saveFile, False),
            ("save As", "aA", self.saveAsFile, False),
            ("eXit", "xX", self.exit, False)
        ])
        
    # File Menu event handlers
    def saveFile(self, *args):
        with open(self._filename, 'wb') as f:
            f.write(self._data_bytes)
        self._modified = False
        
    def saveAsFile(self, *args):
        pass
        # TODO Prompt for filename, update self._filename and then just do normal saveFile
        self.saveFile()

    def exit(self, *args):
        raise ExitProgram()

    def showOptionsMenu(self, stdscr, y, x):
        if self.endian == "big":
            endianTuple = ("set Little endian numbers", "lL", self.toggleEndian, False)
        else:
            endianTuple = ("set Big endian numbers", "bB", self.toggleEndian, False)
        self.showSubMenu(stdscr, y, x, [
            ("Data display format", "dD", self.showDataDisplayFormatMenu, False),
            ("Text display format", "tT", self.showTextDisplayFormatMenu, False),
            ("Offset display format", "oO", self.showOffsetDisplayFormatMenu, False),
            endianTuple,
        ])

    def showDataDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Hex", "hH", partial(self.setDataDisplayFormat, "hex"), self.dataFormat=='hex'),
            ("Decimal", "dD", partial(self.setDataDisplayFormat, "decimal"), self.dataFormat=='decimal'),
            ("Octal", "oO", partial(self.setDataDisplayFormat, "octal"), self.dataFormat=='octal'),
            ("Binary", "bB", partial(self.setDataDisplayFormat, "binary"), self.dataFormat=='binary'),
        ])
    def setDataDisplayFormat(self, df, *args):
        self.dataFormat = df

    def showTextDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Ascii", "aA", partial(self.setTextDisplayFormat, "ascii"), self.textFormat=='ascii'),
            ("Ebcdic", "eE", partial(self.setTextDisplayFormat, "ebcdic"), self.textFormat=='ebcdic'),
        ])
    def setTextDisplayFormat(self, tf, *args):
        self.textFormat = tf

    def showOffsetDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Hex", "hH", partial(self.setOffsetDisplayFormat, "hex"), self.offsetFormat=='hex'),
            ("Decimal", "dD", partial(self.setOffsetDisplayFormat, "decimal"), self.offsetFormat=='decimal'),
        ])
    def setOffsetDisplayFormat(self, of, *args):
        self.offsetFormat = of

    def toggleEndian(self, *args):
        self.endian = "little" if self.endian == "big" else "big"

    def showSearchMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Search...", "sS", self.showSearchFromMenu, False),
            ("Goto offset", "gG", self.showNavigateToOffsetFromMenu, False),
            ("goto Beginning", "bB", self.navigateToBeginning, False),
            ("goto End", "eE", self.navigateToEnd, False),
        ])

    def showSearchFromMenu(self, stdscr, *args):
        self.showSearchDialog(stdscr)
        self.moveCursor(0)

    def showNavigateToOffsetFromMenu(self, stdscr, *args):
        self.showNavigateToOffset(stdscr)
        self.moveCursor(0, normalize=True)

    def navigateToBeginning(self, *args):
        self._cursorPos = 0
        self.moveCursor(0)

    def navigateToEnd(self, *args):
        self._cursorPos = len(self._data_bytes)
        self.moveCursor(0)

    @nomouse
    def showHelp(self, stdscr, *args):
        self.showDialog(stdscr, [
                "Scroll with PgUp, PgDown, Up, Down,",
                "   Right, Left, Home, End",
                "",
                "Navigate directly with Ctrl-G",
                "Search with Ctrl-F",
                "",
                "Exit with Ctrl-C",
                "",
                "Modify by typing in the data or text area.",
                "   Write modified file with Ctrl-W",
                "",
                "Open Menu with F10",
                "",
                "Data display: %s" % self.dataFormat,
                "Text display: %s" % self.textFormat.upper(),
                "Offset display: %s" % self.offsetFormat,
                "Endian: %s" % self.endian,
            ])

    @nomouse
    def showSubMenu(self, stdscr, y, x, menuOptions):
        width = max([len(text) for text, key, subMenuCall, isSelected in menuOptions])
        subMenuWin = stdscr.subwin(len(menuOptions)+1, width+5, y, x)
        subMenuWin.erase()
        for row, (text, key, subMenuCall, isSelected) in enumerate(menuOptions):
            subMenuWin.addstr(row, 1, text + ('*' if isSelected else ''))
        subMenuWin.refresh()
        key = subMenuWin.getkey()
        for row, (text, menuKey, subMenuCall, isSelected) in enumerate(menuOptions):
            if key in menuKey and not isSelected:
                subMenuCall(stdscr, y+row, x+width)
                break

    @nomouse
    def showMainMenu(self, stdscr):
        menuOptions=[
            ("File", 'fF', self.showFileMenu),
            ("Options", 'oO', self.showOptionsMenu),
            ("Search", 'sS', self.showSearchMenu),
            ("Help", 'hH', partial(self.showHelp, stdscr)),
        ]
        menuOptions2 = []
        menuCol = 0
        for text, menuKey, subMenuCall in menuOptions:
            menuOptions2.append((menuCol, text, menuKey, subMenuCall))
            menuCol += len(text) + 2
        menuWin = stdscr.subwin(1, menuCol+5, 0, 0)
        menuWin.erase()
        for menuCol, text, menuKey, subMenuCall in menuOptions2:
            menuWin.addstr(0, menuCol, text)
        menuWin.refresh()
        key = menuWin.getkey()
        for menuCol, text, menuKey, subMenuCall in menuOptions2:
            if key in menuKey:
                subMenuCall(stdscr, 1, menuCol+1)
                break


if __name__=="__main__":
    if not sys.stdout.isatty():
        print "This is an interactive tool. Needs a TTY"
        sys.exit(1)
    from argparse import ArgumentParser
    parser = ArgumentParser(description="Interactive hex editor.", epilog="Additional help with F1.", version="0.52")
    parser.add_argument('--debug', '-d', action='store_true', default=False,
            help="Include some keycode debugging output and display info on F11.")
    parser.add_argument('--data-display-format', '--df', dest='dataFormat',
            choices=('hex', 'octal', 'decimal', 'binary'), default='hex',
            help="Format in which to display the numeric value of the bytes")
    parser.add_argument('--text-display-format', '--tf', dest='textFormat',
            choices=('ascii', 'ebcdic'), default='ascii',
            help="Format in which to display text representation of bytes")
    parser.add_argument('--offset-display-format', '--of', dest='offsetFormat',
            choices=('decimal', 'hex'), default='decimal',
            help="Format in which to display the address offset in the file")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--big-endian', action='store_const', dest='endian', const='big',
            help="Interpret multi-byte numbers as big endian")
    group.add_argument('--little-endian', action='store_const', dest='endian', const='little',
            help="Interpret multi-byte numbers as little endian")
    parser.add_argument('--rec-size', type=int, dest='recSize', default=None,
            help="Specify a fixed record size.")
    parser.add_argument('--mailbag', '--mb', action='store_true', default=False,
            help="Do some ePriority mailbag specific parsing. Especially treat 8 digit ASCII hex numbers as timestamps.")
    parser.add_argument('inputFile',
            help="File to edit")
    #parser.add_argument('-w', action="store_true", default=False,
    #        help="Allow editing of the input file.")
    parser.set_defaults(endian='little')
    args = parser.parse_args()

    editor = HexEditor(args.inputFile)
    # Set up display parameters and stuff to start at the beginning.
    editor.textFormat = args.textFormat
    editor.dataFormat = args.dataFormat
    editor.offsetFormat = args.offsetFormat
    editor.endian = args.endian
    editor.mailbag = args.mailbag
    editor.debug = args.debug
    editor.recSize = args.recSize

    try:
        curses.wrapper(editor.mainLoop)
    except (ExitProgram, KeyboardInterrupt):
        pass
    finally:
        # Make sure to send the terminal code to stop sending mouse event
        # escape sequences.
        sys.stdout.write("\x1b[?1000l")
