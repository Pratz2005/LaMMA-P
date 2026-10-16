(define (problem kitchen_cleaning)
  (:domain robot3)
  (:objects
    robot1 robot2 robot3 - robot
    apple_1 bowl_1 cabinet_1 cabinet_10 cabinet_11 cabinet_2 - object
    cabinet_3 cabinet_4 cabinet_5 cabinet_6 cabinet_7 cabinet_8 - object
    cabinet_9 coffeemachine_1 countertop_1 countertop_2 cup_1 diningtable_1 - object
    dishsponge_1 drawer_1 drawer_2 drawer_3 egg_1 faucet_1 - object
    floor_1 fork_1 fridge_1 garbagebag_1 garbagecan_1 kettle_1 - object
    lightswitch_1 location_0 location_100 location_101 location_103 location_104 - object
    location_106 location_108 location_112 location_17 location_3 location_44 - object
    location_60 location_61 location_67 location_77 location_80 location_89 - object
    location_91 location_92 location_98 mug_1 pan_1 peppershaker_1 - object
    plate_1 pot_1 potato_1 saltshaker_1 sink_1 sinkbasin_1 - object
    soapbottle_1 spatula_1 spoon_1 stool_1 stoveburner_1 stoveburner_2 - object
    stoveburner_3 stoveburner_4 stoveknob_1 stoveknob_2 stoveknob_3 stoveknob_4 - object
    toaster_1 tomato_1 window_1 winebottle_1 - object
  )
  (:init
    (object-close fridge_1)
    (openable fridge_1)
    (at robot1 location_0)
    (at-location apple_1 location_100)
    (at-location bowl_1 location_92)
    (at-location cabinet_1 location_101)
    (at-location cabinet_2 location_101)
    (at-location cabinet_3 location_100)
    (at-location cabinet_4 location_89)
    (at-location cabinet_5 location_91)
    (at-location cabinet_6 location_80)
    (at-location cabinet_7 location_100)
    (at-location cabinet_8 location_91)
    (at-location cabinet_9 location_91)
    (at-location cabinet_10 location_44)
    (at-location cabinet_11 location_89)
    (at-location coffeemachine_1 location_100)
    (at-location countertop_1 location_100)
    (at-location countertop_2 location_92)
    (at-location cup_1 location_100)
    (at-location diningtable_1 location_108)
    (at-location dishsponge_1 location_44)
    (at-location drawer_1 location_92)
    (at-location drawer_2 location_100)
    (at-location drawer_3 location_100)
    (at-location egg_1 location_104)
    (at-location faucet_1 location_61)
    (at-location floor_1 location_3)
    (at-location fork_1 location_100)
    (at-location fridge_1 location_98)
    (at-location garbagebag_1 location_106)
    (at-location garbagecan_1 location_60)
    (at-location kettle_1 location_100)
    (at-location mug_1 location_100)
    (at-location pan_1 location_89)
    (at-location peppershaker_1 location_103)
    (at-location plate_1 location_100)
    (at-location pot_1 location_91)
    (at-location potato_1 location_103)
    (at-location saltshaker_1 location_67)
    (at-location sink_1 location_61)
    (at-location sinkbasin_1 location_61)
    (at-location soapbottle_1 location_77)
    (at-location spatula_1 location_80)
    (at-location spoon_1 location_91)
    (at-location stool_1 location_17)
    (at-location stoveburner_1 location_91)
    (at-location stoveburner_2 location_91)
    (at-location stoveburner_3 location_80)
    (at-location stoveburner_4 location_80)
    (at-location stoveknob_1 location_91)
    (at-location stoveknob_2 location_80)
    (at-location stoveknob_3 location_91)
    (at-location stoveknob_4 location_80)
    (at-location toaster_1 location_89)
    (at-location tomato_1 location_89)
    (at-location window_1 location_112)
    (at-location winebottle_1 location_100)
  )
  (:goal
    (and
      (at-location apple_1 fridge_1)
      (switch-off lightswitch_1)
    )
  )
)
