(define (problem example_problem)
  (:domain robot3)
  (:objects
    robot1 robot2 robotx - robot
    armchair_1 armchair_2 book_1 chair_2 chair_3 chair_4 - object
    chair_5 chair_6 coffeetable_1 creditcard_1 desklamp_1 diningtable_1 - object
    drawer_1 drawer_2 floor_1 floorlamp_1 garbagecan_1 houseplant_1 - object
    keychain_1 laptop_1 lightswitch_1 location_0 newspaper_1 painting_1 - object
    pen_1 pencil_1 pillow_1 plate_1 remotecontrol_1 shelf_1 - object
    shelf_2 shelf_3 sidetable_1 sidetable_2 sidetable_3 sofa_1 - object
    statue_1 television_1 tissuebox_1 tvstand_1 vase_1 watch_1 - object
    window_1 window_2 - object
  )
  (:init
    (openable book_1)
    (at robotx location_0)
    (at-location vase_1 sidetable_1)
    (at-location book_1 chair_2)
  )
  (:goal
    (and
      (at-location vase_1 diningtable_1)
      (object-open book_1)
    )
  )
)
