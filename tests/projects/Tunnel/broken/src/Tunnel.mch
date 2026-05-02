/* Tunnel (broken variant for regression test).
 * Same machine as the perfect version; only the implementation is broken.
 */
MACHINE
    Tunnel
CONCRETE_CONSTANTS
    capacity
PROPERTIES
    capacity : INTEGER &
    capacity = 100
ABSTRACT_VARIABLES
    cars
INVARIANT
    cars : 0 .. capacity
INITIALISATION
    cars := 0
OPERATIONS

    car_enter =
    PRE
        cars < capacity
    THEN
        cars := cars + 1
    END;

    car_exit =
    PRE
        cars > 0
    THEN
        cars := cars - 1
    END

END
