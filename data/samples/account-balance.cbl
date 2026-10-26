       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCOUNT-BALANCE.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-MAX-BALANCE           PIC S9(9)V99 VALUE 999999999.99.

       LINKAGE SECTION.
       01  LK-TRANSACTION.
           05 LK-TRANSACTION-TYPE   PIC X.
           05 LK-TRANSACTION-AMOUNT PIC S9(7)V99.
       01  LK-ACCOUNT.
           05 LK-ACCOUNT-BALANCE    PIC S9(9)V99.
           05 LK-ACCOUNT-STATUS     PIC X.
       01  LK-RESULT-CODE           PIC XX.

       PROCEDURE DIVISION USING LK-TRANSACTION
                                LK-ACCOUNT
                                LK-RESULT-CODE.
       APPLY-TRANSACTION.
           MOVE "00" TO LK-RESULT-CODE
           EVALUATE LK-TRANSACTION-TYPE
               WHEN "D"
                   PERFORM APPLY-DEPOSIT
               WHEN "W"
                   PERFORM APPLY-WITHDRAWAL
               WHEN OTHER
                   MOVE "01" TO LK-RESULT-CODE
           END-EVALUATE
           GOBACK.

       APPLY-DEPOSIT.
           IF LK-TRANSACTION-AMOUNT <= ZERO
               MOVE "02" TO LK-RESULT-CODE
           ELSE
               ADD LK-TRANSACTION-AMOUNT TO LK-ACCOUNT-BALANCE
               IF LK-ACCOUNT-BALANCE > WS-MAX-BALANCE
                   MOVE "03" TO LK-RESULT-CODE
               END-IF
           END-IF.

       APPLY-WITHDRAWAL.
           IF LK-TRANSACTION-AMOUNT <= ZERO
               MOVE "02" TO LK-RESULT-CODE
           ELSE
               SUBTRACT LK-TRANSACTION-AMOUNT
                   FROM LK-ACCOUNT-BALANCE
               PERFORM CHECK-OVERDRAFT
           END-IF.

       CHECK-OVERDRAFT.
           IF LK-ACCOUNT-BALANCE < ZERO
               MOVE "H" TO LK-ACCOUNT-STATUS
               MOVE "04" TO LK-RESULT-CODE
           ELSE
               MOVE "A" TO LK-ACCOUNT-STATUS
           END-IF.

