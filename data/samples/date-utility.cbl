       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATE-UTILITY.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATE-PARTS.
           05 WS-YEAR               PIC 9(4).
           05 WS-MONTH              PIC 99.
           05 WS-DAY                PIC 99.

       LINKAGE SECTION.
       01  LK-INPUT-DATE            PIC X(8).
       01  LK-FORMATTED-DATE        PIC X(10).
       01  LK-RESULT-CODE           PIC XX.

       PROCEDURE DIVISION USING LK-INPUT-DATE
                                LK-FORMATTED-DATE
                                LK-RESULT-CODE.
       FORMAT-DATE.
           MOVE LK-INPUT-DATE(1:4) TO WS-YEAR
           MOVE LK-INPUT-DATE(5:2) TO WS-MONTH
           MOVE LK-INPUT-DATE(7:2) TO WS-DAY
           PERFORM VALIDATE-DATE
           IF LK-RESULT-CODE = "00"
               STRING WS-YEAR "-" WS-MONTH "-" WS-DAY
                   DELIMITED BY SIZE INTO LK-FORMATTED-DATE
               END-STRING
           ELSE
               MOVE SPACES TO LK-FORMATTED-DATE
           END-IF
           GOBACK.

       VALIDATE-DATE.
           MOVE "00" TO LK-RESULT-CODE
           IF WS-MONTH < 1 OR WS-MONTH > 12
               MOVE "01" TO LK-RESULT-CODE
           ELSE
               IF WS-DAY < 1 OR WS-DAY > 31
                   MOVE "02" TO LK-RESULT-CODE
               END-IF
           END-IF.
