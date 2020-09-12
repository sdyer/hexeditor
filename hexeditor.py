#!/usr/bin/python
# vim: set et ts=4 sw=4 :
# -*- coding: cp437-*-

import sys
import curses
from curses.textpad import Textbox, rectangle
import time
import string
import struct
from datetime import datetime
import time
from functools import partial

epoch = datetime(1970, 1, 1)

def rawLog(strVal):
    return
    with open('hexEditor.py.log', 'a') as f:
        f.write(strVal)

# XXX Unneeded now.
rowByteCountMap = {
        'hex': 16,
        'decimal': 10,
        'octal': 12,
        'binary': 4,
}
# XXX Unneeded now.
colTextPosStartMap = {
        'hex':     8+1 + 2*16 + 2,
        'decimal': 8+1 + 2*15 + 2,
        'octal':   8+1 + 3*12 + 3,
        'binary':  8+1 + 4*8  + 4,
}
byteDisplayFormatMap = {
        'hex': " ".join(2*[8*"{:02x}"]),
        'decimal': " ".join(2*[5*"{:03d}"]),
        'octal': " ".join(3*[4*"{:03o}"]),
        'binary': " ".join(4*["{:08b}"]),
}
textDisplayFormatMap = {
        'hex': " ".join(2*[8*"{}"]),
        'decimal': " ".join(2*[5*"{}"]),
        'octal': " ".join(3*[4*"{}"]),
        'binary': " ".join(4*["{}"]),
}
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

class ExitProgram(Exception):
    pass

# I am going to assume we can hold the whole thing in memory at once. It would
# be more flexible for very large files to be able to seek through the file
# with just a small buffer, but that makes everything much more complicated
# when editing and maybe not saving.
class HexEditor(object):
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
    def endian(self, tf):
        if not tf in ('big', 'little'):
            raise TypeError("Invalid endian specification: %r" % tf)
        self._endian = tf

    @property
    def mailbag(self):
        return self._mailbag
    @mailbag.setter
    def mailbag(self, mb):
        self._mailbag = bool(mb)

    @property
    def debug(self):
        return self._debug
    @debug.setter
    def debug(self, debug):
        self._debug = bool(debug)

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

    def resize(self, stdscr):
        # Compute all the positions of everything based on the screen size
        self.maxRow, self.maxCol = stdscr.getmaxyx()
        if self.dataFormat == 'hex':
            assert self.maxCol >= 60, "Need at least 60 columns for hex data display (%d)" % self.maxCol 
        elif self.dataFormat == 'decimal':
            assert self.maxCol >= 52, "Need at least 52 columns for decimal data display (%d)" % self.maxCol
        elif self.dataFormat == 'octal':
            assert self.maxCol >= 62, "Need at least 62 columns for decimal data display (%d)" % self.maxCol
        elif self.dataFormat == 'binary':
            assert self.maxCol >= 52, "Need at least 52 columns for decimal data display (%d)" % self.maxCol
        # TODO Insted of failing, set a tooNarrowMessage that redraw will
        # display until we resize the screen larger.
        if curses.is_term_resized(self.maxRow, self.maxCol):
            curses.resizeterm(self.maxRow, self.maxCol)


    def redraw(self, stdscr, normalize=False):
        #stdscr.clear()
        stdscr.erase()

        # normalize is when the data format (in particular) has changed. We
        # will shift the row containing the cursor to the first row.
        dataSectionCount, dataSectionBytes, dataByteColCount, dataDisplayFormat = byteDisplayFormatMap[self.dataFormat]
        rowByteCount = dataSectionCount * dataSectionBytes
        textDisplayFormat = textDisplayFormatMap[self.dataFormat]
        textStartCol = 9 + dataSectionCount*dataSectionBytes*dataByteColCount + dataSectionCount
        if normalize:
            # We must draw frames of size rowByteCount. Likely cursor is not on
            # an even boundary. We will make the first line contain cursor
            self._firstDisplayLine = self._cursorPos // rowByteCount
        firstRowBytePos = self._firstDisplayLine * rowByteCount
        lastRow = self.maxRow-4
        displayRow = 0
        def addstr(row, col, strVal, colornum, addAttr=0):
            attr = curses.A_BOLD if colornum else 0
            stdscr.addstr(row, col, strVal, curses.color_pair(colornum) | attr | addAttr)
            rawLog('row: %r, col: %r, %r (%r)\n' % (row, col, strVal, curses.color_pair(colornum) | attr | addAttr))
        for rowPtr in range(firstRowBytePos, firstRowBytePos + rowByteCount*lastRow, rowByteCount):
            # Get the row offset in the correct format (hex or decimal)
            if self._offsetFormat == 'hex':
                offsetStr = "%08x" % rowPtr
            else:
                offsetStr = "%08d" % rowPtr
            stdscr.addstr(displayRow, 0, offsetStr)

            displayCol = 9
            textDisplayCol = textStartCol
            rowBytePtr = rowPtr
            for dataSection in range(dataSectionCount):
                color_num = 0
                for sectionByteCounter in range(dataSectionBytes):
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
                                dataDisplayFormat.format(ord(self._data_bytes[rowBytePtr])),
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
                    displayCol += dataByteColCount
                    textDisplayCol += 1
                    rowBytePtr += 1
                displayCol += 1
                textDisplayCol += 1


            displayRow += 1

        #stdscr.vline(0, 8, curses.ACS_VLINE, lastRow)
        #stdscr.vline(0, textStartCol-1, curses.ACS_VLINE, lastRow)
        stdscr.vline(0, 8, '|', lastRow)
        stdscr.vline(0, textStartCol-1, '|', lastRow)
        textSepCol = textStartCol + dataSectionCount*dataSectionBytes + dataSectionCount - 1
        #stdscr.hline(lastRow, 0, curses.ACS_HLINE, textSepCol)
        stdscr.hline(lastRow, 0, '-', textSepCol)
        #stdscr.addch(lastRow, 8, curses.ACS_BTEE)
        #stdscr.addch(lastRow, textStartCol-1, curses.ACS_BTEE)
        stdscr.addch(lastRow, 8, '+')
        stdscr.addch(lastRow, textStartCol-1, '+')

        endian = ">" if self.endian == "big" else "<"
        # Draw the Int value area
        valueRow1 = lastRow+1
        (byteSigned,) = struct.unpack(endian+'b', self._data_bytes[self._cursorPos])
        byteSignedStr = "S8: %d" % byteSigned
        (byteUnsigned,) = struct.unpack(endian+'B', self._data_bytes[self._cursorPos])
        byteUnsignedStr = "U8: %d" % byteUnsigned
        stdscr.addstr(valueRow1, 0, byteSignedStr)
        stdscr.addstr(valueRow1+1, 0, byteUnsignedStr)

        wordCol = max(len(byteSignedStr), len(byteUnsignedStr)) + 2
        wordRaw = self._data_bytes[self._cursorPos:self._cursorPos+2]
        if len(wordRaw) == 2:
            (wordSigned,) = struct.unpack(endian+'h', wordRaw)
            wordSignedStr = "S16: %d" % wordSigned
            (wordUnsigned,) = struct.unpack(endian+'H', wordRaw)
            wordUnsignedStr = "U16: %d" % wordUnsigned
        else:
            wordSignedStr = "S16:"
            wordUnsignedStr = "U16:"
        stdscr.addstr(valueRow1, wordCol, wordSignedStr)
        stdscr.addstr(valueRow1+1, wordCol, wordUnsignedStr)

        longCol = wordCol + max(len(wordSignedStr), len(wordUnsignedStr)) + 2
        longRaw = self._data_bytes[self._cursorPos:self._cursorPos+4]
        if len(longRaw) == 4:
            (longSigned,) = struct.unpack(endian+'i', self._data_bytes[self._cursorPos:self._cursorPos+4])
            longSignedStr = "S32: %d" % longSigned
            (longUnsigned,) = struct.unpack(endian+'I', self._data_bytes[self._cursorPos:self._cursorPos+4])
            longUnsignedStr = "U32: %d" % longUnsigned
        else:
            longUnsigned = None
            longSignedStr = "S32:"
            longUnsignedStr = "U32:"
        stdscr.addstr(valueRow1, longCol, longSignedStr)
        stdscr.addstr(valueRow1+1, longCol, longUnsignedStr)

        timeCol = longCol + max(len(longSignedStr), len(longUnsignedStr)) + 2
        # Here we do some ePriority specific timestamp parsing instead if requested.
        if self.mailbag:
            tsChars = self._data_bytes[self._cursorPos:self._cursorPos+8].strip()
            try:
                tsIntVal = int(tsChars, 16)
            except:
                tsIntVal = None
            if len(tsChars) == 8 and tsIntVal is not None:
                tickCount = tsIntVal
                gmTime = time.gmtime(tickCount)
                localTime = time.localtime(tickCount)
                gmTimeStr = time.strftime('UTC: %Y/%m/%d %H:%M:%S', gmTime)
                localTimeStr = time.strftime('CST: %Y/%m/%d %H:%M:%S', localTime)
            else:
                gmTimeStr = "UTC:"
                localTimeStr = "CST:"
        else:
            # TODO At some point work out whether/how to support a 64bit
            # timestamp, which is already common in some environments.
            if longUnsigned:
                tickCount = longSigned
                gmTime = time.gmtime(tickCount)
                localTime = time.localtime(tickCount)
                gmTimeStr = time.strftime('UTC: %Y/%m/%d %H:%M:%S', gmTime)
                localTimeStr = time.strftime('CST: %Y/%m/%d %H:%M:%S', localTime)
            else:
                gmTimeStr = "UTC:"
                localTimeStr = "CST:"
        stdscr.addstr(valueRow1, timeCol, gmTimeStr)
        stdscr.addstr(valueRow1+1, timeCol, localTimeStr)

        # Update the cursor location, etc.
        statusRow = lastRow+3
        curStatusCol = 0
        if self._offsetFormat == 'hex':
            cursorPosStr = "Cursor: %08x" % self._cursorPos
        else:
            cursorPosStr = "Cursor: %08d" % self._cursorPos
        addstr(statusRow, curStatusCol, cursorPosStr, 1, 0)
        curStatusCol += len(cursorPosStr)+2

        modeStr = "Mode:%s" % self.dataFormat[:3].title()
        addstr(statusRow, curStatusCol, modeStr, 1, 0)
        curStatusCol += len(modeStr) + 2

        if self._editChars:
            # Show accumulated edit chars and update curStatusCol
            (colSections, bytesPerSection, charsPerByte, formatStr) = byteDisplayFormatMap[self.dataFormat]
            editCharStr = "[%*s]" % (charsPerByte, self._editChars)
            curStatusCol -= 1
            addstr(statusRow, curStatusCol, editCharStr, 2, 0)
            curStatusCol += len(editCharStr) + 2

        if self._modified:
            curStatusCol -= 1
            addstr(statusRow, curStatusCol, "MOD", 2, 0)
            curStatusCol += 3 + 2

        sizeStr = "Size: %d" % len(self._data_bytes)
        addstr(statusRow, curStatusCol, sizeStr, 1, 0)
        curStatusCol += len(sizeStr) + 2

        if self.debug:
            for ypos, auxLine in enumerate(self.auxData, 6):
                stdscr.addstr(ypos, 75, auxLine)

        # TODO Ultimately we need to know which input area our cursor is on the
        # screen. We are just assuming the data area for now.
        stdscr.move(self._displayCursorRow, self._displayDataCursorCol)
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
        lastRow = self.maxRow-4
        dataSectionCount, dataSectionBytes, dataByteColCount, dataDisplayFormat = byteDisplayFormatMap[self.dataFormat]
        rowByteCount = dataSectionCount * dataSectionBytes
        #firstScreenRowBytes = self._firstDisplayLine * rowByteCount
        #lastScreenRowBytes = firstScreenRowBytes + (lastRow) * rowByteCount - 1
        self._cursorPos += byteCount
        if byteCount >= 0:
            self._cursorPos = min(len(self._data_bytes)-1, self._cursorPos)
            #if self._cursorPos > lastScreenRowBytes:
            #    self._firstDisplayLine += 1
            #self._firstDisplayLine = min(self._firstDisplayLine, len(self._data_bytes)//rowByteCount-lastRow + 1)
        if byteCount <= 0:
            self._cursorPos = max(0, self._cursorPos)
            #if self._cursorPos < firstScreenRowBytes:
            #    self._firstDisplayLine -= 1
            #self._firstDisplayLine = max(self._firstDisplayLine, 0)
        # TODO We need to see if cursorPos in within firstScreenRowBytes and lastScreenRowBytes. If not, we need to co
        cursorLine = self._cursorPos // rowByteCount
        endFirstDisplayLine = max(len(self._data_bytes)//rowByteCount-lastRow + 1, 0)
        lastDisplayLine = self._firstDisplayLine + lastRow - 1

        if normalize or cursorLine < self._firstDisplayLine:
            self._firstDisplayLine = cursorLine
        elif cursorLine > lastDisplayLine:
            self._firstDisplayLine += cursorLine-lastDisplayLine

        self._firstDisplayLine = max(self._firstDisplayLine, 0)
        self._firstDisplayLine = min(self._firstDisplayLine, endFirstDisplayLine)

    def mainLoop(self, stdscr):
        curses.init_pair(1, curses.COLOR_BLUE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_RED, curses.COLOR_BLACK)
        self._editChars = ""
        self._modified = False
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
        # Calling it up front, initializes everything.
        self.resize(stdscr)
        loopCount = 0
        while True:
            lastRow = self.maxRow-4
            dataSectionCount, dataSectionBytes, dataByteColCount, dataDisplayFormat = byteDisplayFormatMap[self.dataFormat]
            rowByteCount = dataSectionCount * dataSectionBytes
            self.redraw(stdscr)
            ch = stdscr.getch()

            if ch == 27:
                ch, key = self.readEscapes(stdscr)
            elif ch > -1:
                key = curses.keyname(ch)

            if ch == -1:
                stdscr.timeout(-1)
                stdscr.clearok(True)
                self.redraw(stdscr)
                continue
            else:
                stdscr.timeout(500)

            if key in '0123456789abcdefABCDEF':
                # Here, we know it is not one of the navigation or control
                # chars. We are editing binary data directly. Skip everything
                # else.
                # Track of modified
                # TODO Accumulate chars (if appropriate for the mode we are in).
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
                self.redraw(stdscr)
            else:
                self._editChars = ""
                if ch == curses.KEY_RESIZE:
                    self.resize(stdscr)
                    self.redraw(stdscr)
                elif ch == curses.KEY_NPAGE or key == 'KEY_NPAGE':
                    # Compute the next page down and set the positions properly and redraw
                    #self._firstDisplayLine += lastRow
                    self.moveCursor(rowByteCount * lastRow)
                    self.redraw(stdscr)
                elif ch == curses.KEY_PPAGE or key == 'KEY_PPAGE':
                    # Compute the previous page up and set the positions properly and redraw
                    #self._firstDisplayLine -= lastRow
                    self.moveCursor(-rowByteCount * lastRow)
                    self.redraw(stdscr)
                elif ch == curses.KEY_DOWN:
                    self.moveCursor(rowByteCount)
                    self.redraw(stdscr)
                elif ch == curses.KEY_UP:
                    self.moveCursor(-rowByteCount)
                    self.redraw(stdscr)
                elif ch == curses.KEY_RIGHT:
                    self.moveCursor(1)
                    self.redraw(stdscr)
                elif ch == curses.KEY_LEFT:
                    self.moveCursor(-1)
                    self.redraw(stdscr)
                elif key == "KEY_HOME":
                    self._cursorPos = 0
                    #self._firstDisplayLine = 0
                    self.moveCursor(0)
                    self.redraw(stdscr)
                elif key == "KEY_END":
                    self._cursorPos = len(self._data_bytes)-1
                    #self._firstDisplayLine = len(self._data_bytes) // rowByteCount - lastRow
                    self.moveCursor(0)
                    self.redraw(stdscr)
                elif key == "\t":
                    # TODO Change the input area to the next one
                    pass
                elif ch == curses.KEY_BTAB:
                    # TODO Change the input area to the previous one
                    pass
                elif key == "^G":
                    # Goto offset. + or - at beginning means relative. Open new
                    # Window to prompt.
                    self.showNavigateToOffset(stdscr)
                    self.moveCursor(0, normalize=True)
                    self.redraw(stdscr)
                elif key == "KEY_F(1)":
                    self.showHelp(stdscr)
                    self.redraw(stdscr)
                elif self.debug and (key == "KEY_F(11)"):
                    self.showDialog(stdscr, [
                        "curses.has_colors() ==> %r" % curses.has_colors(),
                        "curses.can_change_color() ==> %r" % curses.can_change_color(),
                        "curses.COLORS ==> %r" % curses.COLORS,
                    ])
                    self.redraw(stdscr)
                elif key == "KEY_F(10)":
                    self.showMainMenu(stdscr)
                elif key == "^W" and self._modified:
                    # Write the file back out. There are no safety rails here.
                    # If you say write it and you have permission, it does it.
                    self.saveFile()

            loopCount += 1
            self.auxData.append("%d: %s ==> %s" % (loopCount, ch, key))
            del self.auxData[0:-10]

    def makePrintable(self, strVal):
        #return "".join([ch if ch in string.printable else "?" for ch in strVal])
        if self.textFormat == 'ebcdic':
            strVal = strVal.decode('cp1140').encode('cp1252', errors='replace')
        #return strVal if strVal >= " " else "."
        return "".join([ch if ch in string.printable  and ch >= " " else "." for ch in strVal])

    def showDialog(self, stdscr, lineList):
        # TODO Make a new window
        helpWin = stdscr.subwin(20, 50, 2, 5)
        helpWin.erase()
        helpWin.bkgdset(' ')
        helpWin.border('|', '|', '-', '-', '+', '+', '+', '+')
        # XXX For now using this to display useful information
        for lineNum, line in enumerate(lineList, 1):
            helpWin.addstr(lineNum, 1, line)
        helpWin.refresh()
        ch = helpWin.getch()

    def rectangle(self, win, uly, ulx, lry, lrx):
        win.vline(uly+1, ulx, '|', lry-uly-1)
        win.vline(uly+1, lrx, '|', lry-uly-1)
        win.hline(uly, ulx+1, '-', lrx-ulx-1)
        win.hline(lry, ulx+1, '-', lrx-ulx-1)
        win.addch(uly, ulx, '+')
        win.addch(uly, lrx, '+')
        win.addch(lry, ulx, '+')
        win.addch(lry, lrx, '+')

    def showNavigateToOffset(self, stdscr):
        # TODO Make a new window
        navScreen = stdscr.subwin(9, 33, 2, 5)
        navScreen.erase()
        navScreen.bkgdset(' ')
        navScreen.border('|', '|', '-', '-', '+', '+', '+', '+')
        # XXX For now using this to display useful information
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
        # I think it automatically strips spaces, vbut just in case...
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

    def showFileMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Save", "sS", self.saveFile),
            ("save As", "aA", self.saveAsFile),
            ("eXit", "xX", self.exit)
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
            endianTuple = ("set Little endian numbers", "lL", self.toggleEndian)
        else:
            endianTuple = ("set Big endian numbers", "bB", self.toggleEndian)
        self.showSubMenu(stdscr, y, x, [
            ("Data display format", "dD", self.showDataDisplayFormatMenu),
            ("Text display format", "tT", self.showTextDisplayFormatMenu),
            ("Offset display format", "oO", self.showOffsetDisplayFormatMenu),
            endianTuple,
        ])

    def showDataDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Hex", "hH", partial(self.setDataDisplayFormat, "hex")),
            ("Decimal", "dD", partial(self.setDataDisplayFormat, "decimal")),
            ("Octal", "oO", partial(self.setDataDisplayFormat, "octal")),
            ("Binary", "bB", partial(self.setDataDisplayFormat, "binary")),
        ])
    def setDataDisplayFormat(self, df, *args):
        self.dataFormat = df

    def showTextDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Ascii", "aA", partial(self.setTextDisplayFormat, "ascii")),
            ("Ebcdic", "eE", partial(self.setTextDisplayFormat, "ebcdic")),
        ])
    def setTextDisplayFormat(self, tf, *args):
        self.textFormat = tf

    def showOffsetDisplayFormatMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Hex", "hH", partial(self.setOffsetDisplayFormat, "hex")),
            ("Decimal", "dD", partial(self.setOffsetDisplayFormat, "decimal")),
        ])
    def setOffsetDisplayFormat(self, of, *args):
        self.offsetFormat = of

    def toggleEndian(self, *args):
        self.endian = "little" if self.endian == "big" else "big"

    def showSearchMenu(self, stdscr, y, x):
        self.showSubMenu(stdscr, y, x, [
            ("Goto offset", "gG", self.showNavigateToOffsetFromMenu),
            ("goto Beginning", "bB", self.navigateToBeginning),
            ("goto End", "eE", self.navigateToEnd),
        ])

    def showNavigateToOffsetFromMenu(self, stdscr, *args):
        self.showNavigateToOffset(stdscr)
        self.moveCursor(0, normalize=True)

    def navigateToBeginning(self, *args):
        self._cursorPos = 0
        self.moveCursor(0)

    def navigateToEnd(self, *args):
        self._cursorPos = len(self._data_bytes)
        self.moveCursor(0)

    def showHelp(self, stdscr, *args):
        self.showDialog(stdscr, [
                "Scroll with PgUp, PgDown, Up, Down,",
                "   Right, Left, Home, End",
                "",
                "Navigate directly with Ctrl-G",
                "",
                "Exit with Ctrl-C",
                "",
                "Modify by typing in the data area. Write",
                "   modified file with Ctrl-W",
                "",
                "Open Menu with F10",
            ])

    def showSubMenu(self, stdscr, y, x, menuOptions):
        width = max([len(text) for text, key, subMenuCall in menuOptions])
        subMenuWin = stdscr.subwin(len(menuOptions)+1, width+5, y, x)
        subMenuWin.erase()
        for row, (text, key, subMenuCall) in enumerate(menuOptions):
            subMenuWin.addstr(row, 1, text)
        subMenuWin.refresh()
        key = subMenuWin.getkey()
        for row, (text, menuKey, subMenuCall) in enumerate(menuOptions):
            if key in menuKey:
                subMenuCall(stdscr, y+row, x+width)
                break

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
    parser = ArgumentParser(description="Interactive hex editor. Additional help with F1.")
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

    try:
        curses.wrapper(editor.mainLoop)
    except (ExitProgram, KeyboardInterrupt):
        pass
