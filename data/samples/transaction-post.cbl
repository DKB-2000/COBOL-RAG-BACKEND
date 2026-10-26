       IDENTIFICATION DIVISION.
       PROGRAM-ID. TRANSACTION-POST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TRANSACTION-IN ASSIGN TO "transactions.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  TRANSACTION-IN.
       01  TRANSACTION-INPUT-RECORD.
           05 TI-ACCOUNT-ID         PIC 9(8).
           05 TI-TYPE               PIC X.
           05 TI-AMOUNT             PIC S9(7)V99.

       WORKING-STORAGE SECTION.
       01  WS-END-OF-FILE           PIC X VALUE "N".
           88 END-OF-TRANSACTIONS   VALUE "Y".
       01  WS-TRANSACTION-COUNT     PIC 99 VALUE ZERO.
       01  WS-INDEX                 PIC 99 VALUE ZERO.
       01  WS-TRANSACTION-TABLE.
           05 WS-TRANSACTION-ENTRY OCCURS 20 TIMES.
              10 WS-ACCOUNT-ID      PIC 9(8).
              10 WS-TYPE            PIC X.
              10 WS-AMOUNT          PIC S9(7)V99.
       01  WS-CALL-TRANSACTION.
           05 WS-CALL-TYPE          PIC X.
           05 WS-CALL-AMOUNT        PIC S9(7)V99.
       01  WS-CALL-ACCOUNT.
           05 WS-CALL-BALANCE       PIC S9(9)V99 VALUE ZERO.
           05 WS-CALL-STATUS        PIC X VALUE "A".
       01  WS-RESULT-CODE           PIC XX.

       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT TRANSACTION-IN
           PERFORM LOAD-TRANSACTIONS UNTIL END-OF-TRANSACTIONS
           CLOSE TRANSACTION-IN
           PERFORM POST-TRANSACTIONS VARYING WS-INDEX FROM 1 BY 1
               UNTIL WS-INDEX > WS-TRANSACTION-COUNT
           GOBACK.

       LOAD-TRANSACTIONS.
           READ TRANSACTION-IN
               AT END
                   SET END-OF-TRANSACTIONS TO TRUE
               NOT AT END
                   IF WS-TRANSACTION-COUNT < 20
                       ADD 1 TO WS-TRANSACTION-COUNT
                       MOVE TI-ACCOUNT-ID TO
                           WS-ACCOUNT-ID(WS-TRANSACTION-COUNT)
                       MOVE TI-TYPE TO
                           WS-TYPE(WS-TRANSACTION-COUNT)
                       MOVE TI-AMOUNT TO
                           WS-AMOUNT(WS-TRANSACTION-COUNT)
                   END-IF
           END-READ.

       POST-TRANSACTIONS.
           MOVE WS-TYPE(WS-INDEX) TO WS-CALL-TYPE
           MOVE WS-AMOUNT(WS-INDEX) TO WS-CALL-AMOUNT
           CALL "ACCOUNT-BALANCE" USING WS-CALL-TRANSACTION
                                        WS-CALL-ACCOUNT
                                        WS-RESULT-CODE
           PERFORM HANDLE-POST-RESULT.

       HANDLE-POST-RESULT.
           EVALUATE WS-RESULT-CODE
               WHEN "00" CONTINUE
               WHEN "04" DISPLAY "ACCOUNT ON HOLD: "
                                  WS-ACCOUNT-ID(WS-INDEX)
               WHEN OTHER DISPLAY "TRANSACTION REJECTED: "
                                  WS-ACCOUNT-ID(WS-INDEX)
           END-EVALUATE.

