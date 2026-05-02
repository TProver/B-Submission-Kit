/* Airlock_pressure_bs
 * Author: author_name
 * Creation date: creation_date
 */
MACHINE
    Airlock_pressure_bs
SETS
    PRESSURE = {indoor_pressure, outdoor_pressure, other_pressure}
OPERATIONS
    
    pres <-- get_pressure =
    BEGIN
        pres :: PRESSURE
    END
END
