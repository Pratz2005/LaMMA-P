(define (problem example_problem)
  (:domain robot3)
  (:objects
    robot1 robot2 robot3 - robot
    armchair_1 armchair_2 book_1 bowl_1 box_1 chair_1 - object
    chair_2 chair_3 chair_4 chair_5 chair_6 coffeetable_1 - object
    creditcard_1 desklamp_1 diningtable_1 drawer_1 drawer_2 floorlamp_1 - object
    garbagecan_1 houseplant_1 keychain_1 laptop_1 lightswitch_1 location_0 - object
    location_124 location_130 location_136 location_150 location_160 location_164 - object
    location_167 location_173 location_181 location_189 location_191 location_193 - object
    location_195 location_213 location_226 location_229 location_23 location_230 - object
    location_232 location_233 location_47 location_57 location_70 location_75 - object
    location_77 location_78 location_93 location_99 newspaper_1 painting_1 - object
    pen_1 pencil_1 pillow_1 plate_1 remotecontrol_1 shelf_1 - object
    shelf_2 shelf_3 sidetable_1 sidetable_2 sidetable_3 sofa_1 - object
    statue_1 television_1 tissuebox_1 tvstand_1 vase_1 watch_1 - object
    window_1 window_2 - object
  )
  (:init
    (object-close drawer_1)
    (at robot1 location_0)
    (at robot2 location_0)
    (at robot3 location_0)
    (at-location watch_1 sidetable_3)
    (at-location keychain_1 sidetable_1)
    (openable watch_1)
    (pickupable watch_1)
    (openable keychain_1)
    (pickupable keychain_1)
    (openable drawer_1)
    (pickupable drawer_1)
    (openable drawer_2)
    (pickupable drawer_2)
  )
  (:goal
    (and
      (at-location watch_1 drawer_1)
      (at-location keychain_1 drawer_1)
    )
  )
)
