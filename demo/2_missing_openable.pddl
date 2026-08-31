(define (problem example_problem)
  (:domain robot3)
  (:objects
    robot1 robot2 - robot
    armchair_1 armchair_2 book_1 bowl_1 box_1 chair_1 - object
    chair_2 chair_3 chair_4 chair_5 chair_6 coffeetable_1 - object
    creditcard_1 curtains_1 desklamp_1 diningtable_1 drawer_1 drawer_2 - object
    floor_1 floorlamp_1 garbagecan_1 houseplant_1 keychain_1 laptop_1 - object
    lightswitch_1 location_0 newspaper_1 painting_1 pen_1 pencil_1 - object
    pillow_1 plate_1 remotecontrol_1 shelf_1 shelf_2 shelf_3 - object
    sidetable_1 sidetable_2 sidetable_3 sofa_1 statue_1 television_1 - object
    tissuebox_1 tvstand_1 vase_1 watch_1 window_1 window_2 - object
  )
  (:init
    (at-location vase_1 sidetable_1)
    (at-location book_1 chair_2)
    (at robot1 location_0)
    (at-location vase_1 sidetable_1)
    (at-location book_1 chair_2)
  )
  (:goal
    (and
      (object-open robot2 book_1)
    )
  )
)
