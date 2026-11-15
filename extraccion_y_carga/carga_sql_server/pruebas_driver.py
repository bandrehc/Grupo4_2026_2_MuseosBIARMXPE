"""Pruebas sintéticas exclusivamente en tablas temporales de sesión; no contaminan el corpus."""
import pyodbc
from cargar import connect,scalar,jdump,HERE

def main():
    c=connect()
    c.execute('CREATE TABLE #datos(id nvarchar(20) COLLATE Latin1_General_100_BIN2 PRIMARY KEY,texto nvarchar(max) NOT NULL)')
    c.execute('CREATE TABLE #checkpoint(id int PRIMARY KEY)');c.commit()
    values=[('ABC',''),('abc','áñ漢字🙂,"\nsegunda línea\r\n'+'x'*5000)]
    cur=c.cursor();cur.fast_executemany=True
    cur.setinputsizes([(pyodbc.SQL_WVARCHAR,20,0),(pyodbc.SQL_WLONGVARCHAR,6000,0)])
    cur.executemany('INSERT #datos VALUES(?,?)',values)
    c.execute('INSERT #checkpoint VALUES(1)');c.rollback()
    assert scalar(c,'SELECT COUNT(*) FROM #datos')==0
    assert scalar(c,'SELECT COUNT(*) FROM #checkpoint')==0
    cur.executemany('INSERT #datos VALUES(?,?)',values)
    c.execute('INSERT #checkpoint VALUES(1)');c.commit()
    fetched=[tuple(r) for r in c.cursor().execute('SELECT id,texto FROM #datos ORDER BY id').fetchall()]
    assert fetched==values
    assert scalar(c,'SELECT COUNT(*) FROM #checkpoint')==1
    c.close()
    jdump(HERE/'pruebas_driver.json',{'estado':'OK','Unicode_largo_multilinea_comillas_vacios':'lectura exacta','claves_case_sensitive':'ABC y abc conservados','rollback_filas_y_checkpoint':'ambos cero','commit_filas_y_checkpoint':'ambos confirmados','ubicacion':'tablas temporales de sesión; eliminadas al cerrar conexión'})
    print('Pruebas de driver y atomicidad: OK')

if __name__=='__main__':main()
