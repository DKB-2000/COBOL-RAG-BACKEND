       IDENTIFICATION DIVISION.
       PROGRAM-ID. DAILY-REPORT.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-IN ASSIGN TO "accounts.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-OUT ASSIGN TO "daily-report.txt"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  ACCOUNT-IN.
       01  ACCOUNT-INPUT-RECORD.
           05 AR-ACCOUNT-ID         PIC 9(8).
           05 AR-BALANCE            PIC S9(9)V99.
           05 AR-STATUS             PIC X.
       FD  REPORT-OUT.
       01  REPORT-OUTPUT-RECORD      PIC X(80).

       WORKING-STORAGE SECTION.
       01  WS-END-OF-FILE            PIC X VALUE "N".
           88 END-OF-ACCOUNTS        VALUE "Y".
       01  WS-RUN-DATE               PIC X(8) VALUE "20261001".
       01  WS-FORMATTED-DATE          PIC X(10).
       01  WS-DATE-RESULT             PIC XX.
       01  WS-SUMMARY.
           05 WS-ACCOUNT-COUNT       PIC 9(6) VALUE ZERO.
           05 WS-ACTIVE-COUNT        PIC 9(6) VALUE ZERO.
           05 WS-HOLD-COUNT          PIC 9(6) VALUE ZERO.
           05 WS-TOTAL-BALANCE       PIC S9(11)V99 VALUE ZERO.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           PERFORM FORMAT-REPORT-DATE
           OPEN INPUT ACCOUNT-IN OUTPUT REPORT-OUT
           PERFORM READ-AND-SUMMARIZE UNTIL END-OF-ACCOUNTS
           PERFORM WRITE-SUMMARY
           CLOSE ACCOUNT-IN REPORT-OUT
           GOBACK.

       FORMAT-REPORT-DATE.
           CALL "DATE-UTILITY" USING WS-RUN-DATE
                                     WS-FORMATTED-DATE
                                     WS-DATE-RESULT.

       READ-AND-SUMMARIZE.
           READ ACCOUNT-IN
               AT END
                   SET END-OF-ACCOUNTS TO TRUE
               NOT AT END
                   ADD 1 TO WS-ACCOUNT-COUNT
                   ADD AR-BALANCE TO WS-TOTAL-BALANCE
                   IF AR-STATUS = "A"
                       ADD 1 TO WS-ACTIVE-COUNT
                   ELSE
                       ADD 1 TO WS-HOLD-COUNT
                   END-IF
           END-READ.

       WRITE-SUMMARY.
           STRING "DATE=" WS-FORMATTED-DATE
                  " ACCOUNTS=" WS-ACCOUNT-COUNT
                  " ACTIVE=" WS-ACTIVE-COUNT
                  " HOLD=" WS-HOLD-COUNT
                  " BALANCE=" WS-TOTAL-BALANCE
               DELIMITED BY SIZE INTO REPORT-OUTPUT-RECORD
           END-STRING
           WRITE REPORT-OUTPUT-RECORD.
