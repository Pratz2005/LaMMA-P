(define (domain robot3)
  (:requirements :strips :typing :negative-preconditions) 
  (:types robot object)
  (:predicates
    (at ?robot - robot ?object - object)
    (inaction ?robot - robot)
    (holding ?robot - robot ?object - object)
    (at-location  ?object - object ?location - object)
    ; --- world state -------------------------------------------------------
    ; These describe the state of an OBJECT, not a relationship between a robot
    ; and an object: a light is off, a drawer is open. Indexing them by robot
    ; (the form inherited from the LaMMA-P domain) had two costs. It made goals
    ; unstateable without naming an agent, which KGLAMP's goal stage is not
    ; given - its own example goal is (watch, in, drawer), with no robot - and
    ; it meant a closed container had to be asserted closed once per robot or a
    ; second robot could reach inside it. Both disappear when the state belongs
    ; to the object.
    (switch-on ?object - object)
    (switch-off ?object - object)
    (object-open ?object - object)
    (object-close ?object - object)
    (break ?object - object)
    (sliced ?object - object)
    (cleaned ?object - object)

    ; --- affordances -------------------------------------------------------
    ; The domain previously modelled only object STATE (object-open /
    ; object-close) and never AFFORDANCE. That made a closed container and a
    ; non-openable object indistinguishable to the planner, so the
    ; `openable` flag AI2-THOR provides - and that the property graph
    ; faithfully extracts as (has_capability X openable) - had nowhere to go
    ; and was dropped when building the problem file.
    ;
    ; Only `openable` is used as a precondition (on OpenObject / CloseObject).
    ; The others are declarable so the problem file can record them, but they do
    ; not gate actions: gating every action makes any dropped capability fatal,
    ; which masks the more interesting case where a hallucination still yields a
    ; runnable-but-wrong plan.
    ;
    ; This is the "missing affordance" failure the LaMMA-P paper describes:
    ; encoding a box as closed without recording that it is openable leaves the
    ; planner unable to retrieve its contents. Declaring the affordance makes
    ; the distinction expressible, and makes an omission detectable.
    (openable ?object - object)
    (pickupable ?object - object)
    (sliceable ?object - object)
    (toggleable ?object - object)
  )
  
  (:action GoToObject
    :parameters (?robot - robot ?object - object)
    :precondition (not (inaction ?robot))

    :effect (and 
              (at ?robot ?object)
              (forall (?another_object - object)
                (when (at ?robot ?another_object)
                  (not (at ?robot ?another_object))
                )
              )
              (not (inaction ?robot))
            )
  )

  (:action PickupObject
    :parameters (?robot - robot ?object - object ?location - object)
    :precondition (and
                    (at-location ?object ?location)
                    (at ?robot ?location)
                    (not(inaction ?robot))
                    (not (object-close ?location))
    )
    :effect (and
              (holding ?robot ?object)
              (not(inaction ?robot))
    )
  )

  (:action PutObject
    :parameters (?robot - robot ?object  - object ?location - object)
    :precondition (and
                    (holding ?robot ?object)
                    (at ?robot ?location)
                    (not(inaction ?robot))
                    (not (object-close ?location))
    )
    :effect (and
              (at-location ?object ?location)
              (not (holding ?robot ?object))
              (not(inaction ?robot))
    )
  )
  
  (:action SwitchOn
    :parameters (?robot - robot ?object - object)
    :precondition (and 
                    (not(inaction ?robot))
                    (at ?robot ?object)
    )   
    :effect (and
              (not(inaction ?robot))
              (switch-on ?object)
              (not (switch-off ?object))
    ) 
  )


  (:action Switchoff
    :parameters (?robot - robot ?object - object)
    :precondition (and
                    (not(inaction ?robot))
                    (at ?robot ?object)
    )
    :effect (and
                (not(inaction ?robot))
                (switch-off ?object)
                (not (switch-on ?object))
    )    
  )


  (:action OpenObject
    :parameters (?robot - robot ?object - object)
    :precondition (and
                    (not(inaction ?robot))
                    (at ?robot ?object)
                    (openable ?object)
    )

    :effect (and
                (not(inaction ?robot))
                (object-open ?object)
                (not (object-close ?object))
    )
  )


  (:action BreakObject
    :parameters (?robot - robot ?object - object)
    :precondition (and
                    (not(inaction ?robot))
                    (at ?robot ?object)
    )
    :effect (and
              (not(inaction ?robot))
              (break ?object)
    )
  )
 

  (:action CloseObject
    :parameters (?robot - robot ?object - object)
    :precondition (and
                    (not(inaction ?robot))
                    (at ?robot ?object)
                    (openable ?object)
    )
    :effect (and
              (not(inaction ?robot))
              (object-close ?object)
              (not (object-open ?object))
  )
  )


  (:action SliceObject
    :parameters (?robot - robot ?object - object ?location - object)
    :precondition (and
                    (at-location ?object ?location)
                    (at ?robot ?location)
                    (not(inaction ?robot))
    )
    :effect (and
              (not(inaction ?robot))
              (sliced ?object)
    )
  )    

 (:action CleanObject
    :parameters (?robot - robot ?object - object)
    :precondition (and
                    (not(inaction ?robot))
                    (at ?robot ?object)
    )
    :effect (and
              (not(inaction ?robot))
              (cleaned ?object)
    )    
  )
)