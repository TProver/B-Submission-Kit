/* Tunnel
 * Cars enter and leave a one-way tunnel with a fixed capacity.
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
