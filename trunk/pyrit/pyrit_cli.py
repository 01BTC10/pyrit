# -*- coding: UTF-8 -*-
#
#    Copyright 2008, 2009, Lukas Lueg, lukas.lueg@gmail.com
#
#    This file is part of Pyrit.
#
#    Pyrit is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    Pyrit is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with Pyrit.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import with_statement

import getopt
import hashlib
import itertools
import os
import random
import sys
import threading
import time

import cpyrit.cpyrit_util as util
try:
    import cpyrit.cpyrit_pckttools as pckttools
except util.ScapyImportError:
    pass

class PyritRuntimeError(RuntimeError):
    pass

class Pyrit_CLI(object):
    class options(object):
        def __init__(self):
            self.essidstore_path = os.path.expanduser(os.path.join('~','.pyrit','blobspace','essid'))
            self.passwdstore_path = os.path.expanduser(os.path.join('~','.pyrit','blobspace','password'))
            self.essid = None
            self.bssid = None
            self.file = None
            self.capturefile = None
            self.verbose = True

    def __init__(self):
        # I *hate* the lookup syntax in the code further below if options is a dict
        self.options = self.options()
        
    def tell(self, text, sep=' ', end='\n', stream=sys.stdout, flush=False):
        if self.options.verbose or stream != sys.stdout:
            stream.write(text)
            if end is not None:
                stream.write(end)
            else:
                if sep is not None:
                    stream.write(sep)
            if flush or end is None:
                stream.flush()
        
    def initFromArgv(self):
        options, commands = getopt.getopt(sys.argv[1:], 'u:v:c:e:f:r:b:')
        for option, value in dict(options).items():
            if option == '-e':
                self.options.essid = value
            elif option == '-b':
                self.options.bssid = value
            elif option == '-f':
                self.options.file = value
            elif option == '-r':
                self.options.capturefile = value
            else:
                self.tell("Option '%s' not known. Ignoring..." % option, stream=sys.stderr)
        if self.options.file == '-' or 'passthrough' in commands:
            self.options.verbose = False

        self.essidstore = util.EssidStore(self.options.essidstore_path)
        self.passwdstore = util.PasswordStore(self.options.passwdstore_path)

        self.tell("Pyrit %s (C) 2008, 2009 Lukas Lueg http://pyrit.googlecode.com\n" \
                  "This code is distributed under the GNU General Public License v3\n" % util.VERSION)
        if len(self.essidstore) == 0 and len(commands) > 0 and commands[0] != 'create_essid':
            self.tell('The ESSID-blobspace seems to be empty; you should create an ESSID...\n', stream=sys.stderr)

        {'export_cowpatty': self.export_cowpatty,
         'export_hashdb': self.export_hashdb,
         'export_passwords': self.export_passwords,
         'import_passwords': self.import_passwords,
         'list_cores': self.list_cores,
         'list_essids': self.list_essids,
         'create_essid': self.create_essid,
         'delete_essid': self.delete_essid,
         'eval': self.eval_results,
         'batch': self.batchprocess,
         'batchprocess': self.batchprocess,
         'passthrough': self.passthrough,
         'benchmark': self.benchmark,
         'selftest': self.selftest,
         'verify': self.verify,
         'analyze': self.analyzeCapture,
         'attack_db': self.attack_db,
         'attack_batch': self.attack_batch,
         'attack_passthrough': self.attack_passthrough,
         'help': self.print_help
        }.setdefault(commands[0] if len(commands) > 0 else 'help', self.print_help)()

    def print_help(self):
        self.tell('Usage: pyrit [options] command'
            '\n'
            '\nRecognized options:'
            '\n  -e    : ESSID'
            '\n  -b    : BSSID'
            "\n  -f    : filename for input/output ('-' is stdin/stdout)"
            "\n  -r    : packet capture file in pcap format"
            '\n'
            '\nRecognized commands:'
            '\n  analyze            : Analyze a packet-capture file'
            '\n  attack_db          : Attack a handshake with PMKs from the db'
            '\n  attack_batch       : Attack a handshake with PMKs/passwords from the db'
            '\n  attack_passthrough : Attack a handshake with passwords from a file'
            '\n  batch              : Batchprocess the database'
            '\n  benchmark          : Determine performance of available cores'
            '\n  create_essid       : Create a new ESSID'
            '\n  delete_essid       : Delete a ESSID and corresponding results'
            '\n  eval               : Count the available passwords and matching results'
            '\n  export_cowpatty    : Export results to a new cowpatty file'
            '\n  export_hashdb      : Export results to an airolib database'
            '\n  export_passwords   : Export passwords to a file'
            '\n  import_passwords   : Import passwords from a file'
            '\n  list_cores         : List available cores'
            "\n  list_essids        : List all ESSIDs but don't count matching results"
            '\n  passthrough        : Compute PMKs on the fly and write to stdout'
            '\n  selftest           : Test all cores to ensure they compute correct results'
            '\n  verify             : Verify 10% of the results by recomputation'
            '\n')

    def requires_options(*reqs):
        """Decorate a function to check for certain options before execution."""
        def check_req(f):
            def new_f(*args, **kwds):
                for req in reqs:
                    if not args[0].options.__getattribute__(req):
                        raise PyritRuntimeError(
                                {'essid': "You must specify a ESSID using the option -e. See 'help'.",
                               'file': "You must specify a filename using the option -f. See 'help'.",
                               'capturefile': "You must specify a packet-capture file using the option -r. See 'help'." 
                                }[req])
                f(*args, **kwds)
            new_f.func_name = f.func_name
            return new_f
        return check_req

    def requires_pckttools(*params):
        """Decorate a function to check for cpyrit.cpyrit_pckttools before execution."""
        def check_pkttools(f):
            def new_f(*args, **kwds):
                if 'cpyrit.cpyrit_pckttools' not in sys.modules:
                    raise PyritRuntimeError("The scapy-module is required to use Pyrit's analyze/attack functions but seems to be unavailable.")
                f(*args, **kwds)
            new_f.func_name = f.func_name
            return new_f
        return check_pkttools

    def _printCoreStats(self, cp, startTime):
        totalResCount = sum((c.resCount for c in cp.cores))
        if totalResCount > 0:
            tdiff = time.time() - startTime
            self.tell("Computed %.2f PMKs/s total." % (totalResCount / tdiff))
            for i, core in enumerate(cp.cores):
               perf = core.resCount / core.compTime if core.compTime > 0 else 0
               rtt = (core.resCount / core.callCount) / perf if core.callCount > 0 and perf > 0 else 0
               self.tell("#%i: '%s': %.1f PMKs/s (Occ. %.1f%%; RTT %.1f)" % \
                            (i+1, core.name, perf, core.compTime * 100.0 / tdiff, rtt))

    def _getParser(self, capturefile):
        self.tell("Parsing file '%s'..." % capturefile, end=None) 
        parser = pckttools.PacketParser(capturefile)
        self.tell("%i packets (%i 802.11-packets), %i APs\n" % (parser.pcktcount, parser.dot11_pcktcount, len(parser)))
        return parser
    
    @requires_options('essid')
    def create_essid(self):
        if self.options.essid in self.essidstore:
            # Not an error for reasons of convenience
            self.tell("ESSID already created")
        else:
            self.essidstore.create_essid(self.options.essid)
            self.tell("Created ESSID '%s'" % self.options.essid)

    @requires_options('essid')
    def delete_essid(self, confirm=True):
        if self.options.essid not in self.essidstore:
            raise PyritRuntimeError("ESSID not found...")
        else:
            if confirm:
                self.tell("All results for ESSID '%s' will be deleted! Continue? [y/N]" % self.options.essid, end=None)
                if sys.stdin.readline().strip() != 'y':
                    self.tell("aborted.")
            self.tell("deleting...")
            del self.essidstore[self.options.essid]
            self.tell("Deleted ESSID '%s'." % self.options.essid)

    def list_cores(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        self.tell("The following cores seem available...")
        for i, core in enumerate(cp.cores):
            self.tell("#%i:  '%s'" % (i+1, core))

    def list_essids(self):
        self.tell("Listing ESSIDs...")
        for i, essid in enumerate(self.essidstore):
            self.tell("#%i:  '%s'" % (i, essid))

    def eval_results(self):
        essid_results = dict.fromkeys(self.essidstore, 0)
        pwcount = 0
        for i, (key, passwords) in enumerate(self.passwdstore.iteritems()):
            pwcount += len(passwords)
            if i % 10 == 0:
                self.tell("Passwords available:\t%i\r" % pwcount, end=None, sep=None)
            for essid in essid_results:
                # Let's assume that the presence of the key in the essidstore means that the file is valid and completed...
                essid_results[essid] += len(passwords) if self.essidstore.containskey(essid, key) else 0
        self.tell("Passwords available:\t%i\n" % pwcount)
        for essid, rescount in sorted(essid_results.iteritems()):
            self.tell("ESSID '%s':\t%i (%.2f%%)" % (essid, rescount, (rescount * 100.0 / pwcount) if pwcount > 0 else 0.0))
        self.tell("")
    
    @requires_options('file')
    def import_passwords(self):
        f = sys.stdin if self.options.file == '-' else open(self.options.file, 'r')
        for i, line in enumerate(f):
            self.passwdstore.store_password(line)
            if i % 100000 == 0:
                self.tell("\r%i lines read." % i, end=None, flush=True)
        f.close()
        self.tell("\r%i lines read. Flushing buffers..." % (i + 1))
        self.passwdstore.flush_buffer()
        self.tell('All done.')

    @requires_options('file')
    def export_passwords(self):
        f = sys.stdin if self.options.file == '-' else open(self.options.file, 'w')
        lines = 0
        with util.AsyncFileWriter(f) as awriter:
            for idx, pwset in enumerate(self.passwdstore.iterpasswords()):
                awriter.write('\n'.join(pwset))
                awriter.write('\n')
                lines += len(pwset)
                self.tell("%i lines written (%.2f%%)\r" % (lines, (idx+1)*100 / len(self.passwdstore)), end=None, sep=None)
            self.tell("\nAll done")
        f.close()
    
    @requires_options('file', 'essid')
    def export_cowpatty(self):
        if self.options.essid not in self.essidstore:
            raise PyritRuntimeError("The ESSID you specified can't be found in the storage.")
        f = sys.stdout if self.options.file == '-' else open(self.options.file, 'wb')
        lines = 0
        self.tell("Exporting to '%s'..." % self.options.file)
        awriter = util.AsyncFileWriter(f)
        try:
            awriter.write(util.genCowpHeader(self.options.essid))
            for results in self.essidstore.iterresults(self.options.essid):
                awriter.write(util.genCowpEntries(results))
                lines += len(results)
                self.tell("\r%i entries written..." % lines, end=None, sep=None)
            self.tell("\r%i entries written. All done." % lines)
        except IOError:
            self.tell("IOError while exporting to stdout ignored...", stream=sys.stderr)
        finally:
            awriter.close()
            f.close()

    @requires_pckttools()
    @requires_options('capturefile')
    def analyzeCapture(self):
        for i, ap in enumerate(self._getParser(self.options.capturefile)):
            self.tell("#%i: AccessPoint %s ('%s')" % (i+1, ap, ap.essid))
            for j, sta in enumerate(ap):
                self.tell("  #%i: Station %s" % (j, sta), end=None, sep=None)
                if ap[sta].iscomplete():
                    self.tell(", handshake found")
                else:
                    self.tell('')
            self.tell('')

    @requires_options('file')
    def export_hashdb(self):
        import sqlite3
        essids = list(self.essidstore) if self.options.essid is None else [self.options.essid]
        con = sqlite3.connect(self.options.file)
        con.text_factory = str
        cur = con.cursor()
        cur.execute('SELECT * FROM sqlite_master')
        tbls = [x[1] for x in cur.fetchall() if x[0] == u'table']
        if u'pmk' not in tbls or u'essid' not in tbls or u'passwd' not in tbls:
            self.tell("The database '%s' seems to be uninitialized. "  % self.options.file +
                      "Trying to create default table-layout...", end=None)
            try:
                cur.execute("CREATE TABLE essid (essid_id INTEGER PRIMARY KEY AUTOINCREMENT, essid TEXT, prio INTEGER DEFAULT 64)")
                cur.execute("CREATE TABLE passwd (passwd_id INTEGER PRIMARY KEY AUTOINCREMENT, passwd TEXT)")
                cur.execute("CREATE TABLE pmk (pmk_id INTEGER PRIMARY KEY AUTOINCREMENT, passwd_id INT, essid_id INT, pmk BLOB)")
                cur.execute("CREATE TABLE workbench (wb_id INTEGER PRIMARY KEY AUTOINCREMENT, essid_id INT, passwd_id INT, lockid INTEGER DEFAULT 0)")
                cur.execute("CREATE INDEX lock_lockid ON workbench (lockid);")
                cur.execute("CREATE UNIQUE INDEX essid_u ON essid (essid)")
                cur.execute("CREATE UNIQUE INDEX passwd_u ON passwd (passwd)")
                cur.execute("CREATE UNIQUE INDEX ep_u ON pmk (essid_id, passwd_id)")
                cur.execute("CREATE UNIQUE INDEX wb_u ON workbench (essid_id, passwd_id)")
                cur.execute("CREATE TRIGGER delete_essid DELETE ON essid BEGIN DELETE FROM pmk WHERE pmk.essid_id = OLD.essid_id; DELETE FROM workbench WHERE workbench.essid_id = OLD.essid_id; END;")
                cur.execute("CREATE TRIGGER delete_passwd DELETE ON passwd BEGIN DELETE FROM pmk WHERE pmk.passwd_id = OLD.passwd_id; DELETE FROM workbench WHERE workbench.passwd_id = OLD.passwd_id; END;")
                self.tell("Tables created...")
            except:
                con.rollback()
                cur.close()
                con.close()
                self.tell("Failed to initialize the database:", stream=sys.stderr)
                raise
        try:
            cur.execute("PRAGMA synchronous = 1")
            i = 0
            print "Writing passwords..."
            for pwset in self.passwdstore.iterpasswords():
                i += len(pwset)
                cur.executemany('INSERT OR IGNORE INTO passwd (passwd) VALUES (?)', [(pw,) for pw in pwset])
                self.tell("Wrote %i lines...\r" % i, end=None, sep=None)
            print "\nWriting ESSIDs and results..."
            for essid in essids:
                self.tell("Writing '%s'..." % essid)
                cur.execute('INSERT OR IGNORE INTO essid (essid) VALUES (?)', (essid,))
                essid_id = cur.execute('SELECT essid_id FROM essid WHERE essid = ?', (essid,)).fetchone()[0]
                i = 0
                for results in self.essidstore.iterresults(essid):
                    i += len(results)
                    cur.executemany('INSERT OR IGNORE INTO pmk (essid_id, passwd_id, pmk) SELECT ?, passwd_id, ? FROM passwd WHERE passwd = ?',
                                    ((essid_id, buffer(pmk), pw) for pw, pmk in results))
                    self.tell("Wrote %i lines...\r" % i, end=None, sep=None)
            print "\nAll done."
        except:
            con.rollback()
            self.tell("There was an error while exporting. The database has not been modified...", stream=sys.stderr)
            raise
        else:
            con.commit()
        finally:
            cur.close()
            con.close()

    def _fuzzyGetAP(self, parser):
        if not self.options.bssid and not self.options.essid:
            raise PyritRuntimeError("Specify a AccessPoint's BSSID or ESSID using the options -b or -e. See 'help'")
        if self.options.bssid:
            if self.options.bssid not in parser:
                raise PyritRuntimeError, "No AccessPoint with BSSID '%s' found in the capture file..."
            ap = parser[self.options.bssid]
        else:
            ap = None
        if self.options.essid:
            if not ap:
                aps = filter(lambda ap:(not ap.essid or ap.essid == self.options.essid) and len(ap) > 0, parser)
                if len(aps) > 0:
                    ap = aps[0]
                    self.tell("Picked AccessPoint %s automatically..." % ap)
                else:
                    raise PyritRuntimeError("No suitable AccessPoint with that ESSID in the capture file...")
            else:
                if ap.essid and ap.essid != self.options.essid:
                    self.tell("Warning: AccessPoint %s has ESSID '%s'. Using '%s' anyway..." % (ap, ap.essid, self.options.essid), stream=sys.stderr)
        else:
            if not ap.essid:
                raise PyritRuntimeError("The ESSID for AccessPoint %s is not known from the capture file. Specify it using the option -e." % ap)
            self.options.essid = ap.essid
        return ap

    def _databaseIterator(self, essid, cp, yieldOldResults=True, yieldNewResults=True):
        workunits = []        
        for key in self.passwdstore:
            if yieldOldResults and self.essidstore.containskey(essid, key):
                yield self.essidstore[essid, key]
            elif yieldNewResults:
                passwords = self.passwdstore[key]
                workunits.append((essid, key, passwords))
                cp.enqueue(essid, passwords)
                solvedPMKs = cp.dequeue(block=False)
                if solvedPMKs is not None:
                    solvedEssid, solvedKey, solvedPasswords = workunits.pop(0)
                    solvedResults = zip(solvedPasswords, solvedPMKs)
                    self.essidstore[solvedEssid, solvedKey] = solvedResults
                    yield solvedResults
        if yieldNewResults:
            for solvedPMKs in cp:
                solvedEssid, solvedKey, solvedPasswords = workunits.pop(0)
                solvedResults = zip(solvedPasswords, solvedPMKs)
                self.essidstore[solvedEssid, solvedKey] = solvedResults
                yield solvedResults

    def _passthroughIterator(self, essid, cp, f):
        workunits = []
        pwbuffer = set()
        for line in f:
            pw = line.strip()[:63]
            if len(pw) >= 8:
                pwbuffer.add(pw)
            if len(pwbuffer) > 20000:
                workunits.append(pwbuffer)
                cp.enqueue(essid, workunits[-1])
                pwbuffer = set()
                solvedPMKs = cp.dequeue(block=False)
                if solvedPMKs is not None:
                    yield zip(workunits.pop(0), solvedPMKs)
        if len(pwbuffer) > 0:
            workunits.append(pwbuffer)
            cp.enqueue(essid, workunits[-1])
        for solvedPMKs in cp:
            yield zip(workunits.pop(0), solvedPMKs)

    @requires_options('essid', 'file')
    def passthrough(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        f = sys.stdin if self.options.file == '-' else open(self.options.file, 'r')
        totalResCount = 0
        startTime = time.time()
        awriter = util.AsyncFileWriter(sys.stdout)       
        try:
            awriter.write(util.genCowpHeader(self.options.essid))
            for results in self._passthroughIterator(self.options.essid, cp, f):
                awriter.write(util.genCowpEntries(results))
                totalResCount += len(results)
                self.tell("Computed %i PMKs so far; %i PMKs per second.\r" % \
                            (totalResCount, totalResCount / (time.time() - startTime)), end=None, sep=None)
            self._printCoreStats(cp, startTime)
        except IOError:
            self.tell("IOError while writing to stdout ignored...", stream=sys.stderr)
        finally:
            awriter.close()
            f.close()

    def batchprocess(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        if self.options.file and not self.options.essid:
            raise PyritRuntimeError("Results will be written to a file while batchprocessing. This requires to specify a single ESSID.")
        if self.options.essid is not None:
            if self.options.essid not in self.essidstore:
                self.essidstore.create_essid(self.options.essid)
            essids = [self.options.essid]
        else:
            essids = list(self.essidstore)
        totalResCount = 0
        startTime = time.time()
        workunits = []
        if self.options.file:
            f = sys.stdout if self.options.file == '-' else open(self.options.file, 'wb')
            awriter = util.AsyncFileWriter(f)
        else:
            f = None
        try:
            for essid in essids:
                self.tell("Working on ESSID '%s'" % essid)
                if f:
                    awriter.write(util.genCowpHeader(essid))
                for results in self._databaseIterator(essid, cp, yieldOldResults=f is not None):
                    totalResCount += len(results)
                    if f:
                        awriter.writer(util.genCowpEntries(results))
                    self.tell("Processed %i PMKs so far; %i PMKs per second.\r" % \
                                (totalResCount, totalResCount / (time.time() - startTime)), end=None, sep=None)
                self.tell('')
        except (KeyboardInterrupt, SystemExit):
            self.tell("Exiting...")
        except IOError:
            self.tell("IOError while batchprocessing. Exiting gracefully...")
        finally:
            if f:
                awriter.close()
                f.close()
            self._printCoreStats(cp, startTime)
        self.tell("Batchprocessing done.")

    @requires_pckttools()
    @requires_options('essid', 'file', 'capturefile')
    def attack_passthrough(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        parser = self._getParser(self.options.capturefile)
        ap = self._fuzzyGetAP(parser)
        if len(ap) == 0:
            raise PyritRuntimeError("No valid handshakes for AccessPoint %s found in the capture file." % ap)
        f = sys.stdin if self.options.file == '-' else open(self.options.file, 'r')
        totalResCount = 0
        startTime = time.time()
        for auth in ap.getCompletedAuthentications():
            cracker = pckttools.EAPOLCracker(auth.version, ap.getpke(auth.sta), auth.keymic, auth.frame)
            self.tell("Attacking handshake with Station %s..." % auth.sta)
            for results in self._passthroughIterator(self.options.essid, cp, f):
                cracker.enqueue(results)
                totalResCount += len(results)
                self.tell("Tried %i PMKs so far; %i PMKs per second.\r" % \
                            (totalResCount, totalResCount / (time.time() - startTime)), end=None, sep=None)
                if cracker.solution:
                    break
            else:
                cracker.join()
                if cracker.solution:
                    break
        if cracker.solution:
            self.tell("\n\nThe password is '%s'.\n" % cracker.solution)
        else:
            raise PyritRuntimeError("\n\nPassword was not found.\n")
        self._printCoreStats(cp, startTime)                

    @requires_pckttools()
    @requires_options('capturefile')
    def attack_batch(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        parser = self._getParser(self.options.capturefile)
        ap = self._fuzzyGetAP(parser)
        if len(ap) == 0:
            raise PyritRuntimeError("No valid handshakes for AccessPoint %s found in the capture file." % ap)
        if self.options.essid not in self.essidstore:
            self.essidstore.create_essid(self.options.essid)
        totalResCount = 0
        startTime = time.time()
        try:
            for auth in ap.getCompletedAuthentications():
                cracker = pckttools.EAPOLCracker(auth.version, ap.getpke(auth.sta), auth.keymic, auth.frame)
                self.tell("Attacking handshake with Station %s..." % auth.sta)
                for results in self._databaseIterator(self.options.essid, cp, yieldOldResults=True, yieldNewResults=True):
                    cracker.enqueue(results)
                    totalResCount += len(results)
                    self.tell("Tried %i PMKs so far; %i PMKs per second.\r" % \
                                (totalResCount, totalResCount / (time.time() - startTime)), end=None, sep=None)
                    if cracker.solution:
                        break
                else:
                    cracker.join()
                    if cracker.solution:
                        break
            if cracker.solution:
                self.tell("\n\nThe password is '%s'.\n" % cracker.solution)
            else:
                raise PyritRuntimeError("\n\nThe password was not found.")
        finally:
            self._printCoreStats(cp, startTime)

    @requires_pckttools()
    @requires_options('capturefile')
    def attack_db(self):
        parser = self._getParser(self.options.capturefile)
        ap = self._fuzzyGetAP(parser)
        if len(ap) == 0:
            raise PyritRuntimeError("No valid handshakes for AccessPoint %s found in the capture file." % ap)
        if self.options.essid not in self.essidstore:
            raise PyritRuntimeError("The ESSID you specified can't be found in the database.")
        totalResCount = 0
        startTime = time.time()
        for auth in ap.getCompletedAuthentications():
            cracker = pckttools.EAPOLCracker(auth.version, ap.getpke(auth.sta), auth.keymic, auth.frame)
            self.tell("Attacking handshake with Station %s..." % auth.sta)
            for results in self._databaseIterator(self.options.essid, cp=None, yieldOldResults=True, yieldNewResults=False):
                cracker.enqueue(results)
                totalResCount += len(results)
                self.tell("Tried %i PMKs so far; %i PMKs per second.\r" % \
                            (totalResCount, totalResCount / (time.time() - startTime)), end=None, sep=None)
                if cracker.solution:
                    break
            else:
                cracker.join()
                if cracker.solution:
                    break
        if cracker.solution:
            self.tell("\n\nThe password is '%s'.\n" % cracker.solution)
        else:
            raise PyritRuntimeError("\n\nPassword was not found.\n")

    def benchmark(self, timeout=60):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        # Burn-in so all modules are forced to load and buffers can calibrate to correct size        
        self.tell("Calibrating...", end=None)
        t = time.time()
        pws = ['barbarbar']*1500
        while time.time() - t < 10:
            cp.enqueue('foo', pws)
            cp.dequeue(block=False)
        for r in cp:
            pass        
        # Minimize scheduling overhead...
        pws = ['barbarbar']*max(min(int(cp.getPeakPerformance()), 50000), 500)

        cp.resetStatistics()
        cycler = itertools.cycle(('\\|/-'))
        t = time.time()
        while time.time() - t < timeout:
            self.tell("\rRunning benchmark for about %i seconds... %s" % (timeout - (time.time() - t), cycler.next()), end=None)
            cp.enqueue('foo', pws)
            cp.dequeue(block=False)
        self.tell('')
        for r in cp:
            pass
        self.tell('')
        self._printCoreStats(cp, t)
    
    def selftest(self, timeout=60):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        self.tell("Cores incorporated in the test:")
        for i, core in enumerate(cp.cores):
            self.tell("#%i:  '%s'" % (i+1, core))
        self.tell("\nRunning selftest...")
        workunits = []
        t = time.time()
        err = False
        while time.time() - t < timeout and not err:
            essid = random.choice(util.PMK_TESTVECTORS.keys())
            pws = [random.choice(util.PMK_TESTVECTORS[essid].keys()) for i in xrange(random.randrange(10, 1000))]
            workunits.append((essid, pws))
            cp.enqueue(essid, pws)
            while True:
                solvedPMKs = cp.dequeue(block=False)
                if solvedPMKs is not None:
                    essid, pws = workunits.pop(0)
                    if [util.PMK_TESTVECTORS[essid][pw] for pw in pws] != list(solvedPMKs):
                        err = True
                        break
                if err or not solvedPMKs:
                    break
        if not err:
            for solvedPMKs in cp:
                essid, pws = workunits.pop(0)
                if [util.PMK_TESTVECTORS[essid][pw] for pw in pws] != list(solvedPMKs):
                    err = True
                    break
        if err or len(workunits) != 0 or len(cp) != 0:
            raise PyritRuntimeError("\n!!! WARNING !!!\n"\
                                "At least some results seem to be invalid. "\
                                "This may be caused by a bug in Pyrit, faulty hardware or malicious network clients. Do not trust this installation...\n")
        else:
            self.tell("\nAll results verified. Your installation seems OK.")
    
    def verify(self):
        from cpyrit import cpyrit
        cp = cpyrit.CPyrit()
        if self.options.essid is not None:
            if self.options.essid not in self.essidstore:
                raise PyritRuntimeError("The ESSID '%s' is not found in the repository" % self.options.essid)
            else:
                essids = [self.options.essid]
        else:
            essids = list(self.essidstore)
        totalResCount = 0
        err = False
        startTime = time.time()
        workunits = []
        try: 
            for essid in essids:
                self.tell("Verifying ESSID '%s'" % essid)
                for key, results in self.essidstore.iteritems(essid):
                    sample = random.sample(results, int(len(results) * 0.1))
                    if len(sample) > 0:
                        pws, pmks = zip(*sample)
                        workunits.append((essid, key, tuple(pmks)))
                        cp.enqueue(essid, pws)
                        solvedPMKs = cp.dequeue(block=False)
                        if solvedPMKs is not None:
                            totalResCount += len(solvedPMKs)
                            testedEssid, testedKey, testedPMKs = workunits.pop(0)
                            if testedPMKs != solvedPMKs:
                                self.tell("Workunit %s for ESSID '%s' seems corrupted." % (testedKey, testedEssid), stream=sys.stderr)
                                err = True
                    tdiff = time.time() - startTime
                    self.tell("Computed %i PMKs so far; %i PMKs per second.\r" % (totalResCount, totalResCount / tdiff), end=None, sep=None)
                for solvedPMKs in cp:
                    totalResCount += len(solvedPMKs)
                    testedEssid, testedKey, testedPMKs = workunits.pop(0)
                    if testedPMKs != solvedPMKs:
                        self.tell("Workunit %s for ESSID '%s' seems corrupted." % (testedKey, testedEssid), stream=sys.stderr)
                        err = True
            self.tell("\nVerified %i PMKs with %.2f PMKs/s." % (totalResCount, totalResCount / (time.time() - startTime)))
        except (KeyboardInterrupt, SystemExit):
            self.tell("Exiting...")
        if err:
            raise PyritRuntimeError(
                    "\nAt least one workunit-file contains invalid results. There are two options now:\n"\
                   "* The results on the disk are corrupted or invalid. You should mistrust the entire repository but at least delete and recompute the offending ESSIDs.\n"\
                   "* The result on the disk are correct but your installation is broken and currently computes invalid results.\n"\
                   "Run 'selftest' for an extensive self-test in order to tell the two options apart."
                   )
        else:
            self.tell("Everything seems OK.")

